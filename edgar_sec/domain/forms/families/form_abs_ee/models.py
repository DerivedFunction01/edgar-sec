"""Domain dataclasses for ABS-EE asset-data companion exhibits."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ExhibitKind(StrEnum):
    """The two asset-data exhibit kinds carried by ABS submissions."""

    EX_102 = "EX-102"
    EX_103 = "EX-103"


@dataclass(frozen=True, slots=True)
class AssetDataSummary:
    """Streamed summary of one asset-data exhibit; the body never loads."""

    kind: ExhibitKind
    asset_class: str | None
    root_tag: str
    record_count: int
    comment_count: int
    comment_chars: int
    cdata_sections: int


@dataclass(frozen=True, slots=True)
class CompanionSignal:
    """Presence of one asset-data exhibit kind on a host submission."""

    exhibit_type: str
    present: bool


__all__ = ["AssetDataSummary", "CompanionSignal", "ExhibitKind"]
