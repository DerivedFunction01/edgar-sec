from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import re

from edgar_sec.domain.forms.common.phrases import (
    PhraseCategory,
    PhraseEffect,
    PhraseRule,
)


@dataclass(frozen=True, slots=True)
class CompiledPhraseSequence:
    pattern: re.Pattern[str]
    group_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CompiledPhraseRule:
    rule: PhraseRule
    sequences: tuple[CompiledPhraseSequence, ...]


@dataclass(frozen=True, slots=True)
class PhraseMatch:
    rule_id: str
    category: PhraseCategory
    effect: PhraseEffect
    family_id: str | None
    section_role: str | None
    source_id: str | None
    start_offset: int
    end_offset: int
    start_line: int
    end_line: int
    matched_text: str
    component_spans: tuple[tuple[int, int], ...]
    previous_lines: tuple[str, ...]
    next_lines: tuple[str, ...]


def _literal_phrase_pattern(phrase: str) -> str:
    tokens = phrase.split()
    return r"(?<!\w)" + r"\s+".join(re.escape(token) for token in tokens) + r"(?!\w)"


def _compile_sequence(
    sequence: tuple[str, ...], max_gap_chars: int
) -> CompiledPhraseSequence:
    group_names = tuple(f"part_{index}" for index in range(len(sequence)))
    parts = [
        f"(?P<{group_name}>{_literal_phrase_pattern(phrase)})"
        for group_name, phrase in zip(group_names, sequence, strict=True)
    ]
    if max_gap_chars:
        joiner = rf"[\s\S]{{0,{max_gap_chars}}}?"
    else:
        joiner = r"\s+"
    return CompiledPhraseSequence(
        re.compile(joiner.join(parts), re.IGNORECASE), group_names
    )


def compile_phrase_rules(
    rules: tuple[PhraseRule, ...],
) -> tuple[CompiledPhraseRule, ...]:
    rule_ids = [rule.rule_id for rule in rules]
    if len(rule_ids) != len(set(rule_ids)):
        raise ValueError("phrase rule ids must be unique")
    return tuple(
        CompiledPhraseRule(
            rule,
            tuple(
                _compile_sequence(sequence, rule.max_gap_chars)
                for sequence in rule.sequences
            ),
        )
        for rule in rules
    )


def _line_context(
    text: str,
    line_starts: tuple[int, ...],
    lines: tuple[str, ...],
    start: int,
    end: int,
    context_lines: int,
) -> tuple[int, int, tuple[str, ...], tuple[str, ...]]:
    start_line = bisect_right(line_starts, start)
    end_line = bisect_right(line_starts, max(start, end - 1))
    previous = tuple(lines[max(0, start_line - context_lines - 1) : start_line - 1])
    following = tuple(lines[end_line : end_line + context_lines])
    return start_line, end_line, previous, following


def match_phrase_rules(
    text: str,
    rules: tuple[CompiledPhraseRule, ...],
    *,
    family_id: str | None = None,
    section_role: str | None = None,
    source_id: str | None = None,
) -> tuple[PhraseMatch, ...]:
    line_starts = (0, *(index + 1 for index, char in enumerate(text) if char == "\n"))
    lines = tuple(text.splitlines())
    matches: list[PhraseMatch] = []
    seen: set[tuple[str, int, int]] = set()

    for compiled in rules:
        rule = compiled.rule
        if rule.family_ids and family_id not in rule.family_ids:
            continue
        if rule.section_roles and section_role not in rule.section_roles:
            continue
        for sequence in compiled.sequences:
            for match in sequence.pattern.finditer(text):
                start, end = match.span()
                identity = (rule.rule_id, start, end)
                if identity in seen:
                    continue
                seen.add(identity)
                start_line, end_line, previous, following = _line_context(
                    text,
                    line_starts,
                    lines,
                    start,
                    end,
                    rule.context_lines,
                )
                matches.append(
                    PhraseMatch(
                        rule_id=rule.rule_id,
                        category=rule.category,
                        effect=rule.effect,
                        family_id=family_id,
                        section_role=section_role,
                        source_id=source_id,
                        start_offset=start,
                        end_offset=end,
                        start_line=start_line,
                        end_line=end_line,
                        matched_text=text[start:end],
                        component_spans=tuple(
                            match.span(group_name)
                            for group_name in sequence.group_names
                        ),
                        previous_lines=previous,
                        next_lines=following,
                    )
                )
    return tuple(
        sorted(
            matches, key=lambda item: (item.start_offset, item.end_offset, item.rule_id)
        )
    )


__all__ = [
    "CompiledPhraseRule",
    "CompiledPhraseSequence",
    "PhraseMatch",
    "compile_phrase_rules",
    "match_phrase_rules",
]
