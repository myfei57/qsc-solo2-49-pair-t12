"""Mutable state owned by the pickling tank."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from ..domain.events import utcnow

if TYPE_CHECKING:
    from .plans import DoseOrder

#: Minimum level, in metres, at which the circulation pump may run.
MIN_LEVEL = 2.5

#: Length of the concentration trend window.
TREND_WINDOW = 8

#: Samples required before the trend is allowed to drive a dosing decision.
TREND_MIN_SAMPLES = 4


@dataclass(frozen=True, slots=True)
class TrendSample:
    """One calibrated concentration reading inside the trend window."""

    value: float
    at: datetime = field(default_factory=utcnow)

    def to_dict(self) -> dict[str, object]:
        return {"value": self.value, "at": self.at.isoformat()}


@dataclass(slots=True)
class TankState:
    level: float = 0.0
    offset: float = 0.0
    valve_open: bool = False
    flushed: bool = False
    trend: list[TrendSample] = field(default_factory=list)
    pending_order: DoseOrder | None = None
    orders: list[DoseOrder] = field(default_factory=list)

    def push_level(self, value: float) -> None:
        self.trend.append(TrendSample(float(value)))
        if len(self.trend) > TREND_WINDOW:
            del self.trend[: len(self.trend) - TREND_WINDOW]

    def trend_values(self) -> list[float]:
        return [sample.value for sample in self.trend]

    def trend_delta(self) -> float:
        """Difference between the newer and older halves of the window."""

        if len(self.trend) < 2:
            return 0.0
        values = self.trend_values()
        half = len(values) // 2
        older = values[:half]
        recent = values[half:]
        return _average(recent) - _average(older)

    def trend_average(self) -> float:
        return _average(self.trend_values())


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)
