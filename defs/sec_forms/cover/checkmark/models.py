"""Immutable models shared by cover checkbox extraction and inference."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from defs.text.checkmarks import (
    RE_RAW_CHECKED,
    RE_RAW_UNCHECKED,
    CheckmarkDecision,
)


class InferenceStatus(StrEnum):
    """Outcome of a cover checkbox constraint evaluation."""

    NOT_APPLICABLE = "not_applicable"
    ABSENT = "absent"
    UNRESOLVED = "unresolved"
    RESOLVED = "resolved"


@dataclass(frozen=True, slots=True)
class CheckboxCandidate:
    """One source checkbox associated with a semantic cover label."""

    semantic_key: str
    source_token: str
    group: str
    state: str | None = None
    answer: str | None = None
    question_key: str | None = None
    glyph_class: str | None = None
    source_region: str = ""
    row: int | None = None
    column: int | None = None
    orientation: str = ""
    date_valid: bool | None = None
    label_span: tuple[int, int] | None = None
    mark_span: tuple[int, int] | None = None
    label_text: str = ""

    @property
    def glyph(self) -> str:
        return self.glyph_class or self.source_token

    @property
    def known_state(self) -> str | None:
        if self.state in {"checked", "unchecked"}:
            return self.state
        if (
            RE_RAW_CHECKED.fullmatch(self.source_token)
            or self.source_token.strip().lower() == "x"
        ):
            return "checked"
        if RE_RAW_UNCHECKED.fullmatch(self.source_token):
            return "unchecked"
        return None


@dataclass(frozen=True, slots=True)
class ConstraintViolation:
    """One violated or skipped constraint with its soft penalty."""

    name: str
    penalty: int
    reason: str
    missing: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HypothesisScore:
    """Decoded state vector and penalty for one glyph assignment."""

    assignment: tuple[tuple[str, str], ...]
    penalty: int
    violations: tuple[ConstraintViolation, ...]
    satisfied: tuple[str, ...]
    states: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class CoverCheckmarkResult:
    """Inspectably resolved or unresolved cover checkbox inference."""

    status: InferenceStatus
    decisions: tuple[CheckmarkDecision, ...] = ()
    facts: tuple[tuple[str, str], ...] = ()
    diagnostics: tuple[str, ...] = ()
    hypotheses: tuple[HypothesisScore, ...] = ()
    penalty: int | None = None
    candidates: tuple[CheckboxCandidate, ...] = ()


@dataclass(frozen=True, slots=True)
class PenaltyScorer:
    """Weights used to choose between otherwise ambiguous glyph hypotheses."""

    binary_xor: int = 1000
    primary_exactly_one: int = 1000
    filer_laf_overlay: int = 300
    report_period: int = 700
    direct_state: int = 5000

    def weight(self, name: str) -> int:
        return getattr(self, name)


DEFAULT_PENALTY_SCORER = PenaltyScorer()


__all__ = [
    "DEFAULT_PENALTY_SCORER",
    "CheckboxCandidate",
    "ConstraintViolation",
    "CoverCheckmarkResult",
    "HypothesisScore",
    "InferenceStatus",
    "PenaltyScorer",
]
