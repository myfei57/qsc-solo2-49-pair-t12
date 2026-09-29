"""Pickling tank controller."""

from __future__ import annotations

from ..bus import EventBus
from ..store.filestore import FileStore
from .concentration import ConcentrationOps
from .dosing import DosingOps
from .level import LevelOps
from .plans import OrderOps
from .rinse import RinseOps
from .state import TankState
from .trend import TrendOps


class Tank(LevelOps, ConcentrationOps, DosingOps, RinseOps, TrendOps, OrderOps):
    """Owns the acid level, the calibration offset and the rinse valve."""

    def __init__(self, store: FileStore, bus: EventBus) -> None:
        self._store = store
        self._bus = bus
        self._state = TankState()

    @property
    def store(self) -> FileStore:
        return self._store

    @property
    def bus(self) -> EventBus:
        return self._bus

    @property
    def data(self) -> TankState:
        return self._state

    def snapshot(self) -> dict[str, object]:
        persisted, _ = self.rinse_persisted()
        pending = self.pending_dose_order()
        return {
            "level": self.level(),
            "rinsing": self.rinsing(),
            "offset": self.offset(),
            "flushed": self.flushed(),
            "trend": self.level_trend(),
            "trendSamples": [sample.to_dict() for sample in self.trend_samples()],
            "trendAverage": self.trend_average(),
            "trendReady": self.trend_ready(),
            "trendMinSamples": self.trend_min_samples(),
            "trendWindow": self.trend_window(),
            "pendingOrder": pending.to_dict() if pending else None,
            "rinsingPersist": persisted.active,
        }
