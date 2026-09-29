"""Mutable state owned by the pickling tank."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.records import ConcentrationSample, DosePlanRecord

#: Minimum level, in metres, at which the circulation pump may run.
MIN_LEVEL = 2.5

#: Length of the level trend window.
TREND_WINDOW = 8

#: Number of calibrated concentration readings kept for dosing decisions.
DOSE_WINDOW = 8

#: Number of settled dosing plans retained for review.
PLAN_HISTORY = 20


@dataclass(slots=True)
class TankState:
    level: float = 0.0
    offset: float = 0.0
    valve_open: bool = False
    flushed: bool = False
    trend: list[float] = field(default_factory=list)
    samples: list[ConcentrationSample] = field(default_factory=list)
    pending_plan: DosePlanRecord | None = None
    plan_history: list[DosePlanRecord] = field(default_factory=list)

    def push_level(self, value: float) -> None:
        self.trend.append(value)
        if len(self.trend) > TREND_WINDOW:
            del self.trend[: len(self.trend) - TREND_WINDOW]

    def trend_delta(self) -> float:
        """Difference between the newer and older halves of the window."""

        if len(self.trend) < 2:
            return 0.0
        half = len(self.trend) // 2
        older = self.trend[:half]
        recent = self.trend[half:]
        return _average(recent) - _average(older)

    def push_sample(self, sample: ConcentrationSample) -> None:
        """Record a calibrated concentration reading, trimming the window."""

        self.samples.append(sample)
        if len(self.samples) > DOSE_WINDOW:
            del self.samples[: len(self.samples) - DOSE_WINDOW]

    def sample_values(self) -> list[float]:
        return [sample.value for sample in self.samples]

    def window_average(self) -> float:
        """Mean of the sampled readings; the basis for the dosing decision."""

        return _average(self.sample_values())

    def window_delta(self) -> float:
        """Newer-half average minus older-half average over the sample window."""

        values = self.sample_values()
        if len(values) < 2:
            return 0.0
        half = len(values) // 2
        return _average(values[half:]) - _average(values[:half])

    def archive_plan(self, plan: DosePlanRecord) -> None:
        """Move a settled plan into the bounded review history."""

        self.pending_plan = None
        self.plan_history.append(plan)
        if len(self.plan_history) > PLAN_HISTORY:
            del self.plan_history[: len(self.plan_history) - PLAN_HISTORY]


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)
