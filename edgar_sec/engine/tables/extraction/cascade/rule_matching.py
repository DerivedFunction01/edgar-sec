"""Policy anchor and label-rule matching over a table's context."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.core.normalize import normalize_text
from edgar_sec.engine.tables.extraction.core.policy import Anchor, LabelRule
from edgar_sec.engine.tables.extraction.core.typed_rows import TypedTable

_HEADING_MAX_CHARS = 90
_HEADING_TAIL_LINES = 3


def caption_text(table: TypedTable) -> str:
    parts = list(table.context.caption_stack)
    parts.extend(table.caption.titles)
    parts.extend(period.label for period in table.periods if period.label is not None)
    return " | ".join(normalize_text(part) for part in parts)


def heading_text(table: TypedTable) -> str:
    lines = [
        normalize_text(line)
        for line in table.context.prose_before.splitlines()
        if line.strip()
    ]
    tail = [
        line for line in lines[-_HEADING_TAIL_LINES:] if len(line) <= _HEADING_MAX_CHARS
    ]
    return " | ".join(tail)


def rule_matches(rule: Anchor | LabelRule, table: TypedTable) -> str | None:
    labels = [normalize_text(row.label) for row in table.rows]
    label_set = {label for label in labels if label}
    if isinstance(rule, LabelRule):
        if any(
            not any(needle in label for label in label_set) for needle in rule.required
        ):
            return None
        if rule.together and not any(
            all(needle in label for needle in rule.together) for label in label_set
        ):
            return None
        if rule.any_of and not any(
            needle in label for label in label_set for needle in rule.any_of
        ):
            return None
        return "label_rule"
    texts = []
    if "caption" in rule.sources:
        texts.append(caption_text(table))
    if "heading" in rule.sources:
        texts.append(heading_text(table))
    joined = " | ".join(texts)
    if any(normalize_text(phrase) in joined for phrase in rule.phrases):
        return "anchor"
    return None
