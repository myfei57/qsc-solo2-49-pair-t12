"""Reviewable, withdrawable acid dosing orders.

A dose is no longer applied the moment the button is pressed.  Submitting a
plan opens an order holding a frozen copy of the trend window it was derived
from.  The order stays ``submitted`` while an operator reviews it; it is
either confirmed (the dose is actually applied) or withdrawn.  Every order,
including withdrawn ones, keeps the exact window slice it was based on.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ..domain.events import Event, utcnow
from ..domain.kinds import EventKind
from ..store.keys import KEY_DOSE_ORDERS
from .dosing import TrendBasis
from .errors import PickleError, PickleErrorCode
from .state import TREND_WINDOW


class DoseStatus(str, Enum):
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    WITHDRAWN = "withdrawn"


@dataclass(frozen=True, slots=True)
class DoseOrder:
    order_id: str
    status: DoseStatus
    dose: float
    volume: float
    target: float
    basis: TrendBasis
    submitted_at: datetime
    decided_at: datetime | None = None
    reason: str = ""

    @property
    def is_open(self) -> bool:
        return self.status is DoseStatus.SUBMITTED

    def to_dict(self) -> dict[str, object]:
        return {
            "orderId": self.order_id,
            "status": self.status.value,
            "dose": self.dose,
            "volume": self.volume,
            "target": self.target,
            "basis": self.basis.to_dict(),
            "submittedAt": self.submitted_at.isoformat(),
            "decidedAt": self.decided_at.isoformat() if self.decided_at else None,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "DoseOrder":
        basis_raw = raw.get("basis", {})
        basis = basis_from_raw(basis_raw if isinstance(basis_raw, dict) else {})
        decided = raw.get("decidedAt")
        try:
            status = DoseStatus(str(raw.get("status", DoseStatus.SUBMITTED.value)))
        except ValueError:
            status = DoseStatus.SUBMITTED
        return cls(
            order_id=str(raw.get("orderId", "")),
            status=status,
            dose=float(raw.get("dose", 0.0)),
            volume=float(raw.get("volume", 0.0)),
            target=float(raw.get("target", 0.0)),
            basis=basis,
            submitted_at=_stamp(raw.get("submittedAt")),
            decided_at=_stamp(decided) if decided else None,
            reason=str(raw.get("reason", "")),
        )


def _stamp(raw: object) -> datetime:
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str):
        return datetime.fromisoformat(raw)
    return utcnow()


def basis_from_raw(raw: dict[str, object]) -> TrendBasis:
    samples = raw.get("samples", ())
    sampled_at = raw.get("sampledAt", ())
    return TrendBasis(
        samples=tuple(float(v) for v in samples) if isinstance(samples, (list, tuple)) else (),
        sampled_at=(
            tuple(str(v) for v in sampled_at)
            if isinstance(sampled_at, (list, tuple))
            else ()
        ),
        average=float(raw.get("average", 0.0)),
        delta=float(raw.get("delta", 0.0)),
        window=int(raw.get("window", TREND_WINDOW)),
        ready=bool(raw.get("ready", False)),
    )


#: A positive half-window delta at or below this is treated as flat noise.
TREND_RECOVERY_EPSILON = 1e-9


class OrderOps:
    """Mixed into :class:`~linecontrol.pickle.tank.Tank`."""

    # -- submission -----------------------------------------------------

    def submit_dose_order(self, volume: float, target: float) -> DoseOrder:
        """Create a reviewable order from the current concentration trend."""

        plan = self.plan_dose(volume, target)
        if not plan.required:
            raise PickleError(
                PickleErrorCode.NO_SHORTFALL,
                f"trend average {plan.current:.3f} already at target {target:.3f}",
            )
        # Flat (delta ~ 0) below target is a genuine deficit; only a clearly
        # climbing recent half means the dip is self-correcting.
        if plan.basis.delta > TREND_RECOVERY_EPSILON:
            raise PickleError(
                PickleErrorCode.TREND_RECOVERING,
                f"concentration trend climbing by {plan.basis.delta:.3f}, "
                "withhold dosing and re-check the trend",
            )
        if self.data.pending_order is not None:
            raise PickleError(
                PickleErrorCode.ORDER_PENDING,
                f"order {self.data.pending_order.order_id} is awaiting review",
            )
        order = DoseOrder(
            order_id=self._next_order_id(),
            status=DoseStatus.SUBMITTED,
            dose=plan.dose,
            volume=float(volume),
            target=float(target),
            basis=plan.basis,
            submitted_at=utcnow(),
        )
        self.data.pending_order = order
        self.data.orders.append(order)
        self._persist_orders()
        self._publish("submitted", order)
        return order

    # -- review ---------------------------------------------------------

    def pending_dose_order(self) -> DoseOrder | None:
        return self.data.pending_order

    def dose_orders(self, limit: int = 0) -> list[DoseOrder]:
        """Most recent orders first; ``limit`` of 0 returns all of them."""

        orders = list(reversed(self.data.orders))
        return orders[:limit] if limit > 0 else orders

    def get_dose_order(self, order_id: str) -> DoseOrder:
        for order in self.data.orders:
            if order.order_id == order_id:
                return order
        raise PickleError(
            PickleErrorCode.ORDER_NOT_FOUND, f"no dose order {order_id!r}"
        )

    # -- decision -------------------------------------------------------

    def confirm_dose_order(self, order_id: str) -> DoseOrder:
        """Apply the planned dose and close the order.

        The pump gate is applied by the line command layer so that this mixin
        stays free of pump wiring.
        """

        order = self._require_open(order_id)
        self.apply_dose(order.dose, order.volume)
        decided = self._close_order(order, DoseStatus.CONFIRMED)
        self._publish("confirmed", decided)
        return decided

    def withdraw_dose_order(self, order_id: str, reason: str = "") -> DoseOrder:
        """Cancel an open order; its trend basis is retained verbatim."""

        order = self._require_open(order_id)
        decided = self._close_order(
            order, DoseStatus.WITHDRAWN, reason=reason or "operator withdrew"
        )
        self._publish("withdrawn", decided, decided.reason)
        return decided

    # -- persistence ----------------------------------------------------

    def restore_orders(self) -> None:
        raw = self.store.load(KEY_DOSE_ORDERS)
        if raw is None or not raw.strip():
            return
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(decoded, list):
            return
        orders: list[DoseOrder] = []
        for item in decoded:
            if isinstance(item, dict):
                orders.append(DoseOrder.from_dict(item))
        self.data.orders = orders
        pending = [order for order in orders if order.is_open]
        self.data.pending_order = pending[-1] if pending else None

    # -- internals ------------------------------------------------------

    def _require_open(self, order_id: str) -> DoseOrder:
        order = self.get_dose_order(order_id)
        if not order.is_open:
            raise PickleError(
                PickleErrorCode.ORDER_CLOSED,
                f"order {order_id} is already {order.status.value}",
            )
        return order

    def _close_order(self, order: DoseOrder, status: DoseStatus, reason: str = "") -> DoseOrder:
        decided = DoseOrder(
            order_id=order.order_id,
            status=status,
            dose=order.dose,
            volume=order.volume,
            target=order.target,
            basis=order.basis,
            submitted_at=order.submitted_at,
            decided_at=utcnow(),
            reason=reason,
        )
        index = self.data.orders.index(order)
        self.data.orders[index] = decided
        if self.data.pending_order is order:
            self.data.pending_order = None
        self._persist_orders()
        return decided

    def _next_order_id(self) -> str:
        return f"D{len(self.data.orders) + 1:04d}"

    def _persist_orders(self) -> None:
        payload = json.dumps(
            [order.to_dict() for order in self.data.orders], ensure_ascii=False
        ).encode("utf-8")
        self.store.save(KEY_DOSE_ORDERS, payload)

    def _publish(self, message: str, order: DoseOrder, text: str = "") -> None:
        detail = text or (
            f"dose {order.dose:.3f} on trend average {order.basis.average:.3f} "
            f"({len(order.basis.samples)} samples)"
        )
        self.bus.publish(
            Event(
                kind=EventKind.PUMP,
                source="pickle",
                message=f"dose-order-{message}",
                payload=order.dose,
            )
        )
        self.bus.publish(
            Event(
                kind=EventKind.AUDIT,
                source="pickle",
                message=f"dose-order-{message} {order.order_id}: {detail}",
                payload=order.dose,
            )
        )
