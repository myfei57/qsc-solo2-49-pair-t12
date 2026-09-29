"""Persisted and in-flight process records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from .events import utcnow


def _stamp(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str):
        return datetime.fromisoformat(raw)
    return utcnow()


def _opt_stamp(raw: Any) -> datetime | None:
    if raw in (None, ""):
        return None
    return _stamp(raw)


@dataclass(frozen=True, slots=True)
class Confirm:
    """Outcome of a strip head alignment check."""

    ok: bool = False
    position: float = 0.0
    at: datetime = field(default_factory=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "position": self.position, "at": self.at.isoformat()}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Confirm":
        return cls(
            ok=bool(raw.get("ok", False)),
            position=float(raw.get("position", 0.0)),
            at=_stamp(raw.get("at")),
        )


@dataclass(frozen=True, slots=True)
class WeldRecord:
    """A completed weld seam."""

    seam_id: str = ""
    position: float = 0.0
    tension: float = 0.0
    heat_input: float = 0.0
    at: datetime = field(default_factory=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seam_id": self.seam_id,
            "position": self.position,
            "tension": self.tension,
            "heat_input": self.heat_input,
            "at": self.at.isoformat(),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "WeldRecord":
        return cls(
            seam_id=str(raw.get("seam_id", "")),
            position=float(raw.get("position", 0.0)),
            tension=float(raw.get("tension", 0.0)),
            heat_input=float(raw.get("heat_input", 0.0)),
            at=_stamp(raw.get("at")),
        )


@dataclass(frozen=True, slots=True)
class TensionSnapshot:
    value: float = 0.0
    gain: float = 1.0
    saved: datetime = field(default_factory=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "gain": self.gain, "saved": self.saved.isoformat()}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TensionSnapshot":
        return cls(
            value=float(raw.get("value", 0.0)),
            gain=float(raw.get("gain", 1.0)),
            saved=_stamp(raw.get("saved")),
        )


@dataclass(frozen=True, slots=True)
class AcidSnapshot:
    level: float = 0.0
    offset: float = 0.0
    saved: datetime = field(default_factory=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {"level": self.level, "offset": self.offset, "saved": self.saved.isoformat()}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AcidSnapshot":
        return cls(
            level=float(raw.get("level", 0.0)),
            offset=float(raw.get("offset", 0.0)),
            saved=_stamp(raw.get("saved")),
        )


@dataclass(frozen=True, slots=True)
class PumpSnapshot:
    running: bool = False
    saved: datetime = field(default_factory=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {"running": self.running, "saved": self.saved.isoformat()}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PumpSnapshot":
        return cls(running=bool(raw.get("running", False)), saved=_stamp(raw.get("saved")))


@dataclass(frozen=True, slots=True)
class TrackSnapshot:
    position: float = 0.0
    seam_id: str = ""
    saved: datetime = field(default_factory=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "seam_id": self.seam_id,
            "saved": self.saved.isoformat(),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TrackSnapshot":
        return cls(
            position=float(raw.get("position", 0.0)),
            seam_id=str(raw.get("seam_id", "")),
            saved=_stamp(raw.get("saved")),
        )


@dataclass(frozen=True, slots=True)
class RinseSnapshot:
    active: bool = False
    saved: datetime = field(default_factory=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {"active": self.active, "saved": self.saved.isoformat()}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RinseSnapshot":
        return cls(active=bool(raw.get("active", False)), saved=_stamp(raw.get("saved")))


@dataclass(frozen=True, slots=True)
class LatchSnapshot:
    interlock: bool = False
    alarm: bool = False
    saved: datetime = field(default_factory=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "interlock": self.interlock,
            "alarm": self.alarm,
            "saved": self.saved.isoformat(),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "LatchSnapshot":
        return cls(
            interlock=bool(raw.get("interlock", False)),
            alarm=bool(raw.get("alarm", False)),
            saved=_stamp(raw.get("saved")),
        )


@dataclass(frozen=True, slots=True)
class ConcentrationSample:
    """One calibrated concentration reading and when it was taken."""

    value: float = 0.0
    at: datetime = field(default_factory=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "at": self.at.isoformat()}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ConcentrationSample":
        return cls(value=float(raw.get("value", 0.0)), at=_stamp(raw.get("at")))


@dataclass(frozen=True, slots=True)
class DoseBasis:
    """The trend window a dosing decision was based on.

    Stored verbatim with every submitted plan so that later reviews and
    withdrawals can still point at the exact readings behind the dose,
    independent of samples that arrive afterwards.
    """

    samples: tuple[ConcentrationSample, ...] = ()
    average: float = 0.0
    current: float = 0.0
    delta: float = 0.0
    window_started: datetime | None = None
    window_ended: datetime | None = None

    def sample_count(self) -> int:
        return len(self.samples)

    def to_dict(self) -> dict[str, Any]:
        return {
            "samples": [sample.to_dict() for sample in self.samples],
            "average": self.average,
            "current": self.current,
            "delta": self.delta,
            "windowStarted": self.window_started.isoformat() if self.window_started else None,
            "windowEnded": self.window_ended.isoformat() if self.window_ended else None,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "DoseBasis":
        samples_raw = raw.get("samples", ())
        samples = tuple(
            ConcentrationSample.from_dict(item)
            for item in samples_raw
            if isinstance(item, dict)
        )
        return cls(
            samples=samples,
            average=float(raw.get("average", 0.0)),
            current=float(raw.get("current", 0.0)),
            delta=float(raw.get("delta", 0.0)),
            window_started=_opt_stamp(raw.get("windowStarted")),
            window_ended=_opt_stamp(raw.get("windowEnded")),
        )


@dataclass(frozen=True, slots=True)
class DosePlanRecord:
    """A submitted acid dosing plan and the outcome it reached.

    Status is one of ``pending`` / ``confirmed`` / ``withdrawn``. Withdrawn
    plans are kept on record and still carry the :class:`DoseBasis` captured
    at submission time.
    """

    plan_id: str = ""
    dose: float = 0.0
    volume: float = 0.0
    target: float = 0.0
    basis: DoseBasis = field(default_factory=DoseBasis)
    status: str = "pending"
    submitted: datetime = field(default_factory=utcnow)
    decided: datetime | None = None
    reason: str = ""

    @property
    def required(self) -> bool:
        return self.dose > 0.0

    @classmethod
    def new_id(cls) -> str:
        return uuid4().hex[:12]

    def to_dict(self) -> dict[str, Any]:
        return {
            "planId": self.plan_id,
            "required": self.required,
            "dose": self.dose,
            "volume": self.volume,
            "target": self.target,
            "basis": self.basis.to_dict(),
            "status": self.status,
            "submitted": self.submitted.isoformat(),
            "decided": self.decided.isoformat() if self.decided else None,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "DosePlanRecord":
        basis_raw = raw.get("basis")
        return cls(
            plan_id=str(raw.get("planId", "")),
            dose=float(raw.get("dose", 0.0)),
            volume=float(raw.get("volume", 0.0)),
            target=float(raw.get("target", 0.0)),
            basis=(
                DoseBasis.from_dict(basis_raw)
                if isinstance(basis_raw, dict)
                else DoseBasis()
            ),
            status=str(raw.get("status", "pending")),
            submitted=_stamp(raw.get("submitted")),
            decided=_opt_stamp(raw.get("decided")),
            reason=str(raw.get("reason", "")),
        )
