"""Replenishment volume planning based on the concentration trend."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import PickleError, PickleErrorCode


@dataclass(frozen=True, slots=True)
class TrendBasis:
    """The window slice a dosing decision was taken against.

    ``samples`` are the calibrated readings, oldest first, that were held in
    the trend window when the plan was submitted.  A withdrawn order keeps
    this slice forever so reviewers can replay exactly what was seen.
    """

    samples: tuple[float, ...]
    sampled_at: tuple[str, ...]
    average: float
    delta: float
    window: int
    ready: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "samples": list(self.samples),
            "sampledAt": list(self.sampled_at),
            "average": self.average,
            "delta": self.delta,
            "window": self.window,
            "ready": self.ready,
        }


@dataclass(frozen=True, slots=True)
class DosePlan:
    required: bool
    dose: float
    current: float
    target: float
    basis: TrendBasis

    def to_dict(self) -> dict[str, object]:
        return {
            "required": self.required,
            "dose": self.dose,
            "current": self.current,
            "target": self.target,
            "basis": self.basis.to_dict(),
        }


class DosingOps:
    """Mixed into :class:`~linecontrol.pickle.tank.Tank`."""

    def trend_basis(self) -> TrendBasis:
        samples = self.trend_samples()
        return TrendBasis(
            samples=tuple(sample.value for sample in samples),
            sampled_at=tuple(sample.at.isoformat() for sample in samples),
            average=self.trend_average(),
            delta=self.level_trend(),
            window=self.trend_window(),
            ready=self.trend_ready(),
        )

    def dose_volume(self, volume: float, target: float) -> float:
        if volume <= 0:
            raise PickleError(PickleErrorCode.TANK_VOLUME, "tank volume must be positive")
        shortfall = target - self.trend_average()
        if shortfall <= 0:
            return 0.0
        return shortfall * volume

    def plan_dose(self, volume: float, target: float) -> DosePlan:
        """Plan from the window average rather than the latest reading.

        A single noisy spike cannot flip the decision: the window must hold
        enough samples and the shortfall is measured against the mean.  The
        rising-trend guard lives in order submission.
        """

        if not self.trend_ready():
            raise PickleError(
                PickleErrorCode.TREND_NOT_READY,
                f"need {self.trend_min_samples()} concentration samples, "
                f"have {len(self.trend_samples())}",
            )
        if volume <= 0:
            raise PickleError(PickleErrorCode.TANK_VOLUME, "tank volume must be positive")
        basis = self.trend_basis()
        shortfall = target - basis.average
        dose = shortfall * volume if shortfall > 0 else 0.0
        return DosePlan(
            required=dose > 0,
            dose=dose,
            current=basis.average,
            target=float(target),
            basis=basis,
        )

    def apply_dose(self, dose: float, volume: float) -> None:
        if volume > 0:
            self.data.level += dose / volume
