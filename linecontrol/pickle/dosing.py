"""Replenishment volume planning and the reviewable plan lifecycle."""

from __future__ import annotations

from ..domain.events import Event
from ..domain.kinds import EventKind
from ..domain.records import DosePlanRecord, utcnow
from ..store.keys import KEY_DOSE_HISTORY, KEY_DOSE_PENDING
from ..store.snapshot import load_json, load_records, save_json, save_records
from .errors import PickleError, PickleErrorCode

#: Plan lifecycle states.
PENDING = "pending"
CONFIRMED = "confirmed"
WITHDRAWN = "withdrawn"


class DosingOps:
    """Mixed into :class:`~linecontrol.pickle.tank.Tank`."""

    def dose_volume(self, volume: float, target: float) -> float:
        if volume <= 0:
            raise PickleError(PickleErrorCode.TANK_VOLUME, "tank volume must be positive")
        shortfall = target - self.concentration_average()
        if shortfall <= 0:
            return 0.0
        return shortfall * volume

    def plan_dose(self, volume: float, target: float) -> DosePlanRecord:
        """Build a plan from the recent concentration window without saving it."""

        if volume <= 0:
            raise PickleError(PickleErrorCode.TANK_VOLUME, "tank volume must be positive")
        basis = self.dose_basis()
        shortfall = target - basis.average
        dose = shortfall * volume if shortfall > 0 else 0.0
        return DosePlanRecord(
            plan_id=DosePlanRecord.new_id(),
            dose=dose,
            volume=float(volume),
            target=float(target),
            basis=basis,
            status=PENDING,
            submitted=utcnow(),
        )

    def submit_dose_plan(self, volume: float, target: float) -> DosePlanRecord:
        """Compute a trend-based plan and hold it for review before dosing."""

        if self.data.pending_plan is not None:
            raise PickleError(
                PickleErrorCode.DOSE_PENDING,
                f"dose plan {self.data.pending_plan.plan_id} is awaiting review",
            )
        plan = self.plan_dose(volume, target)
        if not plan.required:
            raise PickleError(
                PickleErrorCode.DOSE_NOT_REQUIRED,
                (
                    f"window average {plan.basis.average:.3f} already at or "
                    f"above target {plan.target:.3f}"
                ),
            )
        self.data.pending_plan = plan
        self._save_pending(plan)
        self.bus.publish(
            Event(
                kind=EventKind.DOSE,
                source="pickle",
                message="submitted",
                payload=plan.dose,
            )
        )
        return plan

    def pending_dose_plan(self) -> DosePlanRecord | None:
        return self.data.pending_plan

    def confirm_dose_plan(self) -> DosePlanRecord:
        """Apply the held plan once the operator has reviewed its basis."""

        plan = self._require_pending()
        self.apply_dose(plan.dose, plan.volume)
        settled = self._settle(plan, CONFIRMED)
        self.bus.publish(
            Event(
                kind=EventKind.DOSE,
                source="pickle",
                message="confirmed",
                payload=plan.dose,
            )
        )
        return settled

    def withdraw_dose_plan(self, reason: str = "") -> DosePlanRecord:
        """Cancel the held plan, keeping it and the data window it relied on."""

        plan = self._require_pending()
        settled = self._settle(plan, WITHDRAWN, reason=reason)
        self.bus.publish(
            Event(
                kind=EventKind.DOSE,
                source="pickle",
                message="withdrawn",
                payload=plan.dose,
            )
        )
        return settled

    def dose_plan_history(self, limit: int = 0) -> tuple[DosePlanRecord, ...]:
        history = tuple(self.data.plan_history)
        if limit > 0:
            return history[-limit:]
        return history

    def dose_plan(self, plan_id: str) -> DosePlanRecord | None:
        """Look up a plan, including withdrawn ones, by its identifier."""

        pending = self.data.pending_plan
        if pending is not None and pending.plan_id == plan_id:
            return pending
        for plan in reversed(self.data.plan_history):
            if plan.plan_id == plan_id:
                return plan
        return None

    def apply_dose(self, dose: float, volume: float) -> None:
        if volume > 0:
            self.data.level += dose / volume

    def restore_dose_plans(self) -> None:
        """Reload the held plan and the review history at start-up."""

        self.data.plan_history = load_records(
            self.store, KEY_DOSE_HISTORY, DosePlanRecord
        )
        pending, ok = load_json(self.store, KEY_DOSE_PENDING, DosePlanRecord)
        self.data.pending_plan = pending if ok else None

    # -- internals ------------------------------------------------------

    def _require_pending(self) -> DosePlanRecord:
        plan = self.data.pending_plan
        if plan is None:
            raise PickleError(
                PickleErrorCode.DOSE_NOT_FOUND,
                "no dosing plan awaiting review",
            )
        return plan

    def _settle(
        self, plan: DosePlanRecord, status: str, reason: str = ""
    ) -> DosePlanRecord:
        settled = DosePlanRecord(
            plan_id=plan.plan_id,
            dose=plan.dose,
            volume=plan.volume,
            target=plan.target,
            basis=plan.basis,
            status=status,
            submitted=plan.submitted,
            decided=utcnow(),
            reason=reason,
        )
        self.data.archive_plan(settled)
        self.store.save(KEY_DOSE_PENDING, b"")
        save_records(self.store, KEY_DOSE_HISTORY, self.data.plan_history)
        return settled

    def _save_pending(self, plan: DosePlanRecord) -> None:
        save_json(self.store, KEY_DOSE_PENDING, plan)
