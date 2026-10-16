"""Candidate structural section extraction across document lines."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from edgar_sec.engine.document.page_markers.detector import is_page_marker_line
from edgar_sec.engine.forms.cover.structure import is_preceding_continuation
from edgar_sec.engine.forms.sections.models import CandidateKind, SectionCandidate
from edgar_sec.foundation.regex.builder import build_alternation

if TYPE_CHECKING:
    from edgar_sec.domain.forms.common.models import ItemDefinition

_OMITTED_TERMS = (
    "omitted",
    "[omitted]",
    "(omitted)",
    "not applicable",
    "n/a",
    "none",
    "reserved",
    "[reserved]",
)
_OMITTED_ALT = build_alternation(list(_OMITTED_TERMS), auto_escape=True)
_RE_OMITTED = re.compile(rf"\b(?:{_OMITTED_ALT})\b", re.IGNORECASE)

_RE_ITEM_TOKEN = re.compile(r"\b\d+[A-Z]?\b", re.IGNORECASE)
_RE_LEADING_PUNCT = re.compile(r"^[\s:.\-]+")

_RE_ITEM_SINGLE = re.compile(
    r"^\s*(?:[\|+•\t-]\s*)?ITEMS?\s+(\d+[A-Z]?(?:\.\d{1,2})?)\b(?:\s*[:.\-]\s*|\s+)?(?:\(\s*continued\s*\))?(.*)$",
    re.IGNORECASE,
)

_CONJUNCTION = build_alternation(
    [r",\s*(?:and|&)", r"and", r"&", r","], auto_escape=False
)
_RE_ITEM_GROUPED = re.compile(
    rf"\bITEMS?\s+(\d+[A-Z]?(?:(?:\s*{_CONJUNCTION}\s*(?:ITEMS?\s+)?)\d+[A-Z]?)+)\b",
    re.IGNORECASE,
)

_RE_NUMERIC_LABEL = re.compile(
    r"^\s*(?:[\|+•\t-]\s*)?(\d{1,2}[A-Z]?)\.\s+([A-Z][A-Za-z0-9\s,&'-]+)$"
)


def extract_section_candidates(
    lines: list[str],
    *,
    taxonomy_items: tuple[ItemDefinition, ...] = (),
    toc_lines: set[int] | None = None,
) -> list[SectionCandidate]:
    """Scan lines and collect candidate Part/Item structural headings."""
    candidates: list[SectionCandidate] = []
    title_to_item: dict[str, str] = {}
    for item_def in taxonomy_items:
        for name in item_def.names:
            norm_name = " ".join(name.lower().split())
            if len(norm_name) >= 4:
                title_to_item[norm_name] = item_def.item

    for line_no, raw_line in enumerate(lines):
        if toc_lines and line_no in toc_lines:
            continue
        stripped = raw_line.strip()
        if not stripped or is_page_marker_line(stripped):
            continue

        prev_line = lines[line_no - 1] if line_no > 0 else ""
        preceded = is_preceding_continuation(prev_line)

        # Check grouped items (Items 1, 1A, and 1B)
        grouped_match = _RE_ITEM_GROUPED.search(stripped)
        if grouped_match:
            raw_ids = grouped_match.group(0)
            raw_title = _RE_LEADING_PUNCT.sub(
                "", stripped[grouped_match.end() :]
            ).strip()
            item_ids = tuple(token.upper() for token in _RE_ITEM_TOKEN.findall(raw_ids))
            is_omitted = bool(_RE_OMITTED.search(raw_title))
            candidates.append(
                SectionCandidate(
                    line_number=line_no,
                    raw_text=raw_line,
                    kind=CandidateKind.GROUPED,
                    identifiers=item_ids,
                    title=raw_title,
                    is_omitted=is_omitted,
                    preceded_by_continuation=preceded,
                )
            )
            continue

        # Check standard singular item (Item 1. Business)
        single_match = _RE_ITEM_SINGLE.match(stripped)
        if single_match:
            item_id = single_match.group(1).upper()
            raw_title = _RE_LEADING_PUNCT.sub("", single_match.group(2)).strip()
            is_omitted = bool(_RE_OMITTED.search(raw_title))
            if not raw_title and not is_omitted:
                for lookahead in range(line_no + 1, min(line_no + 3, len(lines))):
                    next_s = lines[lookahead].strip()
                    if next_s:
                        norm_next = " ".join(next_s.lower().split())
                        if norm_next in title_to_item or any(
                            norm_next.startswith(k) for k in title_to_item
                        ):
                            raw_title = next_s
                        break
            candidates.append(
                SectionCandidate(
                    line_number=line_no,
                    raw_text=raw_line,
                    kind=CandidateKind.STANDARD,
                    identifiers=(item_id,),
                    title=raw_title,
                    is_omitted=is_omitted,
                    preceded_by_continuation=preceded,
                )
            )
            continue

        # Check numeric label (1. Business)
        numeric_match = _RE_NUMERIC_LABEL.match(stripped)
        if numeric_match:
            num_id = numeric_match.group(1).upper()
            raw_title = numeric_match.group(2).strip()
            norm_title = " ".join(raw_title.lower().split())
            if norm_title in title_to_item or any(
                norm_title.startswith(k) for k in title_to_item
            ):
                is_omitted = bool(_RE_OMITTED.search(raw_title))
                candidates.append(
                    SectionCandidate(
                        line_number=line_no,
                        raw_text=raw_line,
                        kind=CandidateKind.NUMERIC,
                        identifiers=(num_id,),
                        title=raw_title,
                        is_omitted=is_omitted,
                        preceded_by_continuation=preceded,
                    )
                )
                continue

        # Check substantive title only (PROSPECTUS SUMMARY, USE OF PROCEEDS)
        norm_line = " ".join(stripped.lower().split())
        matched_item = title_to_item.get(norm_line)
        if matched_item and len(norm_line) > 5 and not preceded:
            canon_num = matched_item.replace("ITEM", "").strip()
            candidates.append(
                SectionCandidate(
                    line_number=line_no,
                    raw_text=raw_line,
                    kind=CandidateKind.TITLE_ONLY,
                    identifiers=(canon_num,),
                    title=stripped,
                    is_omitted=False,
                    preceded_by_continuation=False,
                )
            )

    return candidates
