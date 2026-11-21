"""Domain model for the ABS text reports (10-D / ABS-15G)."""

from __future__ import annotations

from enum import StrEnum


class FormAbsReportsKind(StrEnum):
    """Which face of the ABS reports family a filing carries."""

    DISTRIBUTION = "distribution"
    SECURITIZER = "securitizer"


__all__ = ["FormAbsReportsKind"]
