"""The classification cascade's decision types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TableKind(Enum):
    """The structural kind a classified table carries."""

    STATEMENT = "statement"
    NOTE_DETAIL = "note_detail"
    PARENTHETICAL = "parenthetical"


@dataclass(frozen=True, slots=True)
class Evidence:
    """One scored contribution to a classification."""

    group: str
    detail: str
    points: float


@dataclass(frozen=True, slots=True)
class Classification:
    """A family decision with flavor, kind, and its evidence trail."""

    family: str
    flavor: str | None
    kind: TableKind
    tier: str
    score: float
    evidence: tuple[Evidence, ...]
