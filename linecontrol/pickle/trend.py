"""Level and concentration trend helpers."""

from __future__ import annotations

from ..domain.records import ConcentrationSample, DoseBasis, utcnow


class TrendOps:
    """Mixed into :class:`~linecontrol.pickle.tank.Tank`."""

    def push_level(self, value: float) -> None:
        self.data.push_level(float(value))

    def level_trend(self) -> float:
        return self.data.trend_delta()

    def push_concentration_sample(self) -> None:
        """Stamp the current calibrated concentration into the trend window."""

        self.data.push_sample(
            ConcentrationSample(value=self.concentration(), at=utcnow())
        )

    def concentration_samples(self) -> tuple[ConcentrationSample, ...]:
        return tuple(self.data.samples)

    def concentration_average(self) -> float:
        """Window average used by the dosing decision rather than one point."""

        return self.data.window_average()

    def concentration_delta(self) -> float:
        return self.data.window_delta()

    def dose_basis(self) -> DoseBasis:
        """Snapshot the window so a plan can be reviewed against it later."""

        samples = self.concentration_samples()
        return DoseBasis(
            samples=samples,
            average=self.data.window_average(),
            current=self.concentration(),
            delta=self.data.window_delta(),
            window_started=samples[0].at if samples else None,
            window_ended=samples[-1].at if samples else None,
        )

    def concentration_window(self) -> dict[str, object]:
        """Read-only projection of the window for the console."""

        basis = self.dose_basis()
        return {
            "samples": [sample.to_dict() for sample in basis.samples],
            "average": basis.average,
            "current": basis.current,
            "delta": basis.delta,
            "windowStarted": basis.window_started.isoformat()
            if basis.window_started
            else None,
            "windowEnded": basis.window_ended.isoformat()
            if basis.window_ended
            else None,
            "windowSize": len(basis.samples),
        }
