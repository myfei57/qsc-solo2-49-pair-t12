"""Concentration trend helpers."""

from __future__ import annotations

from .state import TREND_MIN_SAMPLES, TREND_WINDOW, TrendSample


class TrendOps:
    """Mixed into :class:`~linecontrol.pickle.tank.Tank`."""

    def push_level(self, value: float) -> None:
        self.data.push_level(float(value))

    def level_trend(self) -> float:
        return self.data.trend_delta()

    def trend_window(self) -> int:
        return TREND_WINDOW

    def trend_min_samples(self) -> int:
        return TREND_MIN_SAMPLES

    def trend_samples(self) -> list[TrendSample]:
        return list(self.data.trend)

    def trend_ready(self) -> bool:
        """Whether enough readings exist for a trend-based decision."""

        return len(self.data.trend) >= TREND_MIN_SAMPLES

    def trend_average(self) -> float:
        """Mean calibrated concentration over the current window."""

        return self.data.trend_average()
