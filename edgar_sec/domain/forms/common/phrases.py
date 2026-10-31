from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PhraseCategory(StrEnum):
    FIELD_LABEL = "field_label"
    INSTRUCTION = "instruction"
    WARNING = "warning"
    CERTIFICATION = "certification"
    OMB_NOTICE = "omb_notice"
    TABLE_HEADING = "table_heading"
    BOILERPLATE = "boilerplate"


class PhraseEffect(StrEnum):
    ANNOTATE = "annotate"
    BOUNDARY = "boundary"
    EXCLUDE_FROM_VALUE = "exclude_from_value"


@dataclass(frozen=True, slots=True)
class PhraseRule:
    rule_id: str
    sequences: tuple[tuple[str, ...], ...]
    category: PhraseCategory
    effect: PhraseEffect = PhraseEffect.ANNOTATE
    family_ids: frozenset[str] = frozenset()
    section_roles: frozenset[str] = frozenset()
    max_gap_chars: int = 0
    context_lines: int = 1

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise ValueError("phrase rule id must be non-empty")
        if not self.sequences or any(
            not sequence or any(not part.strip() for part in sequence)
            for sequence in self.sequences
        ):
            raise ValueError("phrase rules require non-empty sequences")
        if self.max_gap_chars < 0 or self.context_lines < 0:
            raise ValueError("phrase matching bounds must be non-negative")


__all__ = ["PhraseCategory", "PhraseEffect", "PhraseRule"]
