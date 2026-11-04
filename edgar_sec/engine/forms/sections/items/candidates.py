"""Candidate structural section extraction across document lines."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from edgar_sec.engine.document.page_markers.detector import is_page_marker_line
from edgar_sec.engine.forms.cover.structure import is_preceding_continuation
from edgar_sec.engine.forms.sections.models import CandidateKind, SectionCandidate
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import MONTH_NAME_RE

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
_RE_LEADING_PUNCT = re.compile(r"^[\s:.\-\u2013\u2014]+")

# Lowercase words that occur in running-head furniture (date phrases and
# status qualifiers) without turning the line into prose.
_FURNITURE_WORDS = frozenset(
    {
        "and",
        "as",
        "at",
        "audited",
        "continued",
        "ended",
        "ending",
        "for",
        "interim",
        "month",
        "months",
        "of",
        "period",
        "quarter",
        "quarterly",
        "the",
        "then",
        "unaudited",
        "year",
        "years",
    }
)
_WORD_EDGE_CHARS = ".,;:()[]\"'\u2013\u2014-|"


def _norm_word(word: str) -> str:
    return word.strip(_WORD_EDGE_CHARS).lower()


def _is_furniture_word(word: str, *, all_caps: bool = False) -> bool:
    """Whether a word is page furniture: a separator, a number or date
    token, a month, a capitalized name word, or a date-phrase word.
    """
    core = word.strip(_WORD_EDGE_CHARS)
    if not core or not any(ch.isalpha() for ch in core):
        return True
    if MONTH_NAME_RE.match(core):
        return True
    if all_caps:
        return False
    if core[0].isupper():
        return True
    return core.lower() in _FURNITURE_WORDS


def _is_signal_word(
    word: str, *, all_caps: bool = False, mid_line: bool = False
) -> bool:
    """Whether a furniture word carries heading signal beyond a bare page
    number: a capitalized name word, a month, or a full date token.
    """
    core = word.strip(_WORD_EDGE_CHARS)
    if not core:
        return False
    if core.lower() in _FURNITURE_WORDS:
        return False
    if MONTH_NAME_RE.match(core):
        return True
    if any(ch.isdigit() for ch in core) and "/" in core:
        return True
    if core.isdigit() and len(core) == 4:
        return True
    if all_caps or mid_line:
        return False
    return sum(ch.isalpha() for ch in core) >= 2 and any(ch.isupper() for ch in core)


_TOKEN_SPLIT_RE = re.compile(r"[\s\u2013\u2014]+")
_DOT_LEADER_RE = re.compile(r"\.{3,}")
_REFERENCE_VERBS = frozenset({"see", "cf", "refer", "refers", "referred", "referring"})


def _match_composite_heading(
    stripped: str,
    title_entries: list[tuple[str, str]],
) -> tuple[str, str] | None:
    """Match a taxonomy title carried by page furniture: TOC-style rows and
    composite running heads, where the title's line-mates are only page
    numbers, dates, and the registrant's own name.
    """
    if '"' in stripped or "'" in stripped or "\u201c" in stripped:
        return None
    if _DOT_LEADER_RE.search(stripped):
        return None
    words = [word for word in _TOKEN_SPLIT_RE.split(stripped) if word]
    if len(words) < 2:
        return None
    alpha_words = [word for word in words if any(ch.isalpha() for ch in word)]
    all_caps = bool(alpha_words) and all(word == word.upper() for word in alpha_words)
    norm_words = [_norm_word(word) for word in words]
    matches: list[tuple[int, str, str, bool]] = []
    for title_norm, key in title_entries:
        title_words = title_norm.split()
        count = len(title_words)
        if count < 1 or count >= len(words):
            continue
        for start in range(0, len(words) - count + 1):
            if norm_words[start : start + count] != title_words:
                continue
            prefix = words[:start]
            suffix = words[start + count :]
            if not prefix and not suffix:
                continue
            if prefix and _norm_word(prefix[-1]) in _REFERENCE_VERBS:
                continue
            if suffix and _norm_word(suffix[0]) in _REFERENCE_VERBS:
                continue
            if not all(_is_furniture_word(word, all_caps=all_caps) for word in prefix):
                continue
            if not all(_is_furniture_word(word, all_caps=all_caps) for word in suffix):
                continue
            if any(_norm_word(word) in {"and", "&"} for word in suffix):
                continue
            if suffix and _norm_word(suffix[0]) in {"of", "and", "&"}:
                continue
            furniture = (*prefix, *suffix)
            if any("$" in word for word in furniture):
                continue
            if any(
                "(" in word
                and word.strip(_WORD_EDGE_CHARS).strip("()").lower()
                not in _FURNITURE_WORDS
                for word in furniture
            ):
                continue
            if not any(
                any(ch.isdigit() for ch in word) or MONTH_NAME_RE.match(word)
                for word in furniture
            ):
                continue
            mid_line = start != 0 and start + count != len(words)
            signal = any(
                _is_signal_word(word, all_caps=all_caps, mid_line=mid_line)
                for word in furniture
            )
            matches.append((count, key, " ".join(words[start : start + count]), signal))
    if not matches:
        return None
    best_count = max(count for count, _, _, _ in matches)
    for count, key, title_text, signal in matches:
        if count == best_count and signal:
            return key, title_text
    return None


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
    # Canonical keys mirror the sequence tracker's own derivation: a
    # title-keyed taxonomy joins ITEM candidates through their titles;
    # an ITEM-keyed taxonomy keeps the filer's own number.
    title_to_key: dict[str, str] = {
        norm_name: item.replace("ITEM", "").strip()
        for norm_name, item in title_to_item.items()
    }
    canonical_keys = set(title_to_key.values())
    title_entries = sorted(
        title_to_key.items(), key=lambda entry: -len(entry[0].split())
    )

    def resolve_identifier(numeric_id: str, norm_title: str) -> str:
        if numeric_id in canonical_keys:
            return numeric_id
        return title_to_key.get(norm_title.rstrip(" ."), numeric_id)

    for line_no, raw_line in enumerate(lines):
        if toc_lines and line_no in toc_lines:
            continue
        stripped = raw_line.strip()
        if (
            not stripped
            or len(stripped) > 200
            or stripped[0].islower()
            or is_page_marker_line(stripped)
        ):
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
                        if norm_next.rstrip(" .") in title_to_item or any(
                            norm_next.startswith(k) for k in title_to_item
                        ):
                            raw_title = next_s
                        break
            norm_title = " ".join(raw_title.lower().split())
            candidates.append(
                SectionCandidate(
                    line_number=line_no,
                    raw_text=raw_line,
                    kind=CandidateKind.STANDARD,
                    identifiers=(resolve_identifier(item_id, norm_title),),
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
            if norm_title.rstrip(" .") in title_to_item or any(
                norm_title.startswith(k) for k in title_to_item
            ):
                is_omitted = bool(_RE_OMITTED.search(raw_title))
                candidates.append(
                    SectionCandidate(
                        line_number=line_no,
                        raw_text=raw_line,
                        kind=CandidateKind.NUMERIC,
                        identifiers=(resolve_identifier(num_id, norm_title),),
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
            continue

        # Check composite headings: the title carried by page furniture
        if not preceded:
            composite = _match_composite_heading(stripped, title_entries)
            if composite is not None:
                key, title_text = composite
                candidates.append(
                    SectionCandidate(
                        line_number=line_no,
                        raw_text=raw_line,
                        kind=CandidateKind.TITLE_ONLY,
                        identifiers=(key,),
                        title=title_text,
                        is_omitted=False,
                        preceded_by_continuation=False,
                    )
                )

    return candidates
