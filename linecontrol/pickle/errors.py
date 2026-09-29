"""Pickling tank failures."""

from __future__ import annotations

from enum import Enum


class PickleErrorCode(str, Enum):
    TANK_VOLUME = "tank-volume"
    OFFSET_INVALID = "offset-invalid"
    DOSE_PENDING = "dose-pending"
    DOSE_NOT_FOUND = "dose-not-found"
    DOSE_NOT_REQUIRED = "dose-not-required"


class PickleError(RuntimeError):
    def __init__(self, code: PickleErrorCode, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "detail": self.detail}
