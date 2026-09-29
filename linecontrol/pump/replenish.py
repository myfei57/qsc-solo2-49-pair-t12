"""Replenishment gate driven by the calibrated concentration."""

from __future__ import annotations

from .errors import PumpError, PumpErrorCode


class ReplenishOps:
    """Mixed into :class:`~linecontrol.pump.pump.Pump`."""

    def replenish_gate(
        self, min_concentration: float, measured: float | None = None
    ) -> None:
        """Refuse a dose request while the tank is already above target.

        ``measured`` is the reading the request was planned against; it
        defaults to the live concentration so direct callers keep working.
        Plan confirmation passes the frozen window average instead, which
        stops a single jumping reading from vetoing a trend-based plan.
        """

        concentration = (
            self.tank.concentration() if measured is None else measured
        )
        if concentration >= min_concentration:
            raise PumpError(
                PumpErrorCode.NO_REPLENISH,
                f"concentration {concentration:.3f} above target {min_concentration:.3f}",
            )
