"""Domain model for Form SD."""

from __future__ import annotations

from enum import StrEnum


class SDKind(StrEnum):
    """Which rule election a filing carries, read off its own face."""

    CONFLICT_MINERALS = "conflict_minerals"
    RESOURCE_EXTRACTION = "resource_extraction"
    COMBINED = "combined"
    UNDETERMINED = "undetermined"


__all__ = ["SDKind"]
