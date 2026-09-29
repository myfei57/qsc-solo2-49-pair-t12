"""Replenishment gate driven by the calibrated concentration."""

from __future__ import annotations

from .errors import PumpError, PumpErrorCode


class ReplenishOps:
    """Mixed into :class:`~linecontrol.pump.pump.Pump`."""

    def replenish_gate(self, min_concentration: float) -> None:
        """Refuse to apply a dose while the live tank is already above target.

        A dose order is planned from a frozen trend window, but confirmation
        re-reads the live concentration: if the tank recovered while the
        order awaited review, applying the dose would overshoot.
        """

        concentration = self.tank.concentration()
        if concentration >= min_concentration:
            raise PumpError(
                PumpErrorCode.NO_REPLENISH,
                f"concentration {concentration:.3f} above target {min_concentration:.3f}",
            )
