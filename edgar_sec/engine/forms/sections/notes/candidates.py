"""Candidate financial statement note extraction across document lines."""

from __future__ import annotations

import re

from edgar_sec.engine.forms.cover.structure import is_preceding_continuation
from edgar_sec.engine.forms.sections.models import CandidateKind, SectionCandidate
from edgar_sec.engine.tables.toc.patterns import (
    RE_NOTE_GROUPED,
    RE_NOTE_HEADING,
    looks_like_toc_tabular,
)

_RE_NOTE_SINGLE = RE_NOTE_HEADING

_RE_NOTE_GROUPED_ANCHORED = re.compile(
    rf"^\s*(?:[\|+•\t-]\s*)?{RE_NOTE_GROUPED.pattern}",
    re.IGNORECASE,
)

_RE_NOTE_NUMERIC = re.compile(
    r"^\s*(?:[\|+•\t-]\s*)?(\d{1,2})\.\s+([A-Z][A-Za-z0-9\s,&'-]+)$"
)

_RE_NOTE_LETTERED = re.compile(
    r"^\s*(?:[\|+•\t-]\s*)?[Nn][Oo][Tt][Ee]\s+([A-Z])\b"
    r"\s*[—–\-:.]\s*([A-Z].*)$"
)

_RE_DIGIT_TOKEN = re.compile(r"\b\d+\b")

_RE_PAGE_TAIL = re.compile(r"(?:(?:\.\s*){2,}|\s{3,})\d{1,4}\s*$")


def extract_note_candidates(
    lines: list[str],
    *,
    start_line: int = 0,
    end_line: int | None = None,
) -> list[SectionCandidate]:
    """Scan lines within financial notes scope and collect Note candidates."""
    candidates: list[SectionCandidate] = []
    limit = end_line if end_line is not None else len(lines)

    for line_no in range(start_line, min(len(lines), limit)):
        raw_line = lines[line_no]
        stripped = raw_line.strip()
        if not stripped:
            continue
        if looks_like_toc_tabular(stripped) or _RE_PAGE_TAIL.search(stripped):
            continue

        prev_line = lines[line_no - 1] if line_no > 0 else ""
        preceded = is_preceding_continuation(prev_line)

        grouped_match = _RE_NOTE_GROUPED_ANCHORED.match(stripped)
        if grouped_match:
            raw_ids = grouped_match.group(0)
            raw_title = stripped[grouped_match.end() :].strip()
            note_ids = tuple(_RE_DIGIT_TOKEN.findall(raw_ids))
            candidates.append(
                SectionCandidate(
                    line_number=line_no,
                    raw_text=raw_line,
                    kind=CandidateKind.GROUPED,
                    identifiers=note_ids,
                    title=raw_title,
                    preceded_by_continuation=preceded,
                )
            )
            continue

        single_match = _RE_NOTE_SINGLE.match(stripped)
        if single_match:
            note_id = single_match.group(1)
            raw_title = single_match.group(2).strip()
            candidates.append(
                SectionCandidate(
                    line_number=line_no,
                    raw_text=raw_line,
                    kind=CandidateKind.STANDARD,
                    identifiers=(note_id,),
                    title=raw_title,
                    preceded_by_continuation=preceded,
                )
            )
            continue

        lettered_match = _RE_NOTE_LETTERED.match(stripped)
        if lettered_match:
            candidates.append(
                SectionCandidate(
                    line_number=line_no,
                    raw_text=raw_line,
                    kind=CandidateKind.STANDARD,
                    identifiers=(lettered_match.group(1),),
                    title=lettered_match.group(2).strip(),
                    preceded_by_continuation=preceded,
                )
            )
            continue

        numeric_match = _RE_NOTE_NUMERIC.match(stripped)
        if numeric_match:
            num_id = numeric_match.group(1)
            raw_title = numeric_match.group(2).strip()
            candidates.append(
                SectionCandidate(
                    line_number=line_no,
                    raw_text=raw_line,
                    kind=CandidateKind.NUMERIC,
                    identifiers=(num_id,),
                    title=raw_title,
                    preceded_by_continuation=preceded,
                )
            )

    return candidates
