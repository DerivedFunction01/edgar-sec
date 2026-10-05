"""Pre-2005 exhibit-candidate detection for requested filing documents.

A verdict names a request worth a bundle inspection and changes no fetch, no
normalization, and no stored row. Outside the 2000-2004 window it is not evidence of
anything, so the policy fails closed rather than guessing.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from functools import lru_cache
from itertools import product

from edgar_sec.domain.document.models import DocumentLocator, FilingOccurrence
from edgar_sec.domain.forms.common.aliases import aliases_for_family, resolve_alias
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import parse_date

#: Sequence-1 exhibit inversion is bounded to this half-open filing-date window.
#: Pre-2000 targets already arrive as bundles; 2005 and later have none observed.
CANDIDATE_WINDOW_START = date(2000, 1, 1)
CANDIDATE_WINDOW_END = date(2005, 1, 1)

_SEPARATOR = r"[-_]?"

_EXHIBIT_PREFIX_ALT = build_alternation(["dex", "exhibit", "ex"], auto_escape=True)
_EXHIBIT_EXT_ALT = build_alternation(["txt", "htm", "html"], auto_escape=True)

#: Item 601 numbers exhibits 1..105. The bound is what separates ``ex21.txt`` from a
#: ticker prefix, so it is part of the grammar rather than a post-filter.
_STATUTORY_NUM_ALT = build_alternation(
    [r"10[0-5]", r"[1-9]\d", r"[1-9]"], auto_escape=False
)

RE_STATUTORY_EXHIBIT_FILENAME = re.compile(
    rf"(?i)^(?:{_EXHIBIT_PREFIX_ALT}){_SEPARATOR}(?:{_STATUTORY_NUM_ALT})"
    rf"(?:[-._][a-z0-9]+)?\.(?:{_EXHIBIT_EXT_ALT})$"
)

_UNITS = (
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
)
_TEENS = (
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
)
_DECADES = (
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
)

#: Filings of the era spelled numbers in words, sometimes omitting the multiplier.
_FAMILY_CONTEXT_TOKENS = {
    "10-K": ("annual",),
    "20-F": ("annual",),
    "10-Q": ("quarterly",),
    "8-K": ("current",),
    "6-K": ("current",),
}
_ALWAYS_TOKENS = ("form", "report")

_ALIAS_SEPARATORS_RE = re.compile(r"[-/ ]+")
_ALIAS_TOKENS_RE = re.compile(r"(\d+|[a-zA-Z]+)")


class CandidateIntent(StrEnum):
    """How far one requested document passes the pre-2005 candidate gate."""

    OUT_OF_WINDOW = "out_of_window"
    WINDOW_ELIGIBLE = "window_eligible"
    BUNDLE_CANDIDATE = "bundle_candidate"


@dataclass(frozen=True, slots=True)
class CandidateDecision:
    """The gate's verdict for one locator, with the reason that produced it.

    Advisory: it is a request worth inspecting, never a claim that the document is
    displaced or that a sibling holds the primary.
    """

    intent: CandidateIntent
    reason: str

    @property
    def window_eligible(self) -> bool:
        """Whether one valid filing date fell inside the window."""
        return self.intent is not CandidateIntent.OUT_OF_WINDOW

    @property
    def is_bundle_candidate(self) -> bool:
        """Whether the filename also reads as a statutory exhibit."""
        return self.intent is CandidateIntent.BUNDLE_CANDIDATE


def occurrence_filing_date(occurrences: Sequence[FilingOccurrence]) -> date | None:
    """Return the one filing date a locator's occurrences agree on, else ``None``.

    Co-filers share a locator, so a disagreement is an unresolvable conflict, and a
    missing or malformed value fails closed rather than substituting the accession year.
    """
    agreed: date | None = None
    for occurrence in occurrences:
        parsed = parse_date(occurrence.filing_date)
        if parsed is None:
            return None
        value = date(
            parsed.components.year, parsed.components.month, parsed.components.day
        )
        if agreed is None:
            agreed = value
        elif agreed != value:
            return None
    return agreed


def _compound(rest: int) -> str:
    """Return the word spelling of ``rest`` for 1..99, delimiter tolerant."""
    if rest <= 9:
        return _UNITS[rest - 1]
    if rest <= 19:
        return _TEENS[rest - 10]
    unit = _UNITS[rest % 10 - 1] if rest % 10 else ""
    return _DECADES[rest // 10 - 2] + (_SEPARATOR + unit if unit else "")


def _num_word_variants(n: int) -> list[str]:
    """Return word-spelled regex variants of ``n``; the digits are the caller's."""
    if n <= 0:
        return []
    if n <= 99:
        return [_compound(n)]
    head = _UNITS[n // 100 - 1]
    rest = n % 100
    if rest == 0:
        return [head + _SEPARATOR + "hundred"]
    spelled = _compound(rest)
    and_clause = rf"(?:{_SEPARATOR}and)?{_SEPARATOR}"
    return [
        head + _SEPARATOR + spelled,
        head + _SEPARATOR + "hundred" + and_clause + spelled,
        "hundred" + and_clause + spelled,
        head + _SEPARATOR + str(rest).zfill(2),
    ]


def _alias_word_patterns(alias: str) -> list[str]:
    """Expand one canonical alias into every delimiter-tolerant spelling."""
    segments: list[list[str]] = []
    for token in _ALIAS_TOKENS_RE.findall(_ALIAS_SEPARATORS_RE.sub("", alias)):
        if not token.isdigit():
            segments.append([token.lower()])
            continue
        options = [token, *_num_word_variants(int(token))]
        segments.append(
            [options[0]]
            if len(options) == 1
            else [build_alternation(options, auto_escape=False)]
        )
    return [_SEPARATOR.join(combo) for combo in product(*segments)]


@lru_cache(maxsize=64)
def _form_token_pattern(family: str | None) -> re.Pattern[str]:
    tokens = list(_ALWAYS_TOKENS)
    if family:
        tokens.extend(_FAMILY_CONTEXT_TOKENS.get(family, ()))
        for alias in (family, *aliases_for_family(family)):
            tokens.extend(_alias_word_patterns(alias))
    return re.compile(rf"(?i){build_alternation(sorted(set(tokens)))}")


def primary_form_token_pattern(form: str | None) -> re.Pattern[str]:
    """Return the pattern whose match marks a filename as the primary form itself.

    Unanchored: a filer who named the primary ``ex-10k.htm`` still means the 10-K,
    so the token disqualifies the candidate wherever it appears in the name.
    """
    return _form_token_pattern(
        resolve_alias(form) or (form.upper().strip() if form else None)
    )


def filename_basename(document_path: str) -> str:
    """Return the path's basename; a rendered route's directory is not filename grammar."""
    return document_path.strip().rsplit("/", 1)[-1]


def candidate_decision(
    locator: DocumentLocator, filing_date: date | None
) -> CandidateDecision:
    """Classify one request against the window and the statutory filename grammar."""
    if filing_date is None:
        return CandidateDecision(CandidateIntent.OUT_OF_WINDOW, "no_filing_date")
    if not CANDIDATE_WINDOW_START <= filing_date < CANDIDATE_WINDOW_END:
        return CandidateDecision(CandidateIntent.OUT_OF_WINDOW, "outside_window")
    name = filename_basename(locator.document_path)
    if not RE_STATUTORY_EXHIBIT_FILENAME.match(name):
        return CandidateDecision(
            CandidateIntent.WINDOW_ELIGIBLE, "not_statutory_exhibit"
        )
    if primary_form_token_pattern(locator.form).search(name):
        return CandidateDecision(CandidateIntent.WINDOW_ELIGIBLE, "primary_form_token")
    return CandidateDecision(CandidateIntent.BUNDLE_CANDIDATE, "statutory_exhibit")


def candidate_for(
    locator: DocumentLocator, occurrences: Sequence[FilingOccurrence]
) -> tuple[date | None, CandidateDecision]:
    """Return the agreed filing date and the gate verdict for one locator."""
    filing_date = occurrence_filing_date(occurrences)
    return filing_date, candidate_decision(locator, filing_date)


__all__ = [
    "CANDIDATE_WINDOW_END",
    "CANDIDATE_WINDOW_START",
    "RE_STATUTORY_EXHIBIT_FILENAME",
    "CandidateDecision",
    "CandidateIntent",
    "candidate_decision",
    "candidate_for",
    "filename_basename",
    "occurrence_filing_date",
    "primary_form_token_pattern",
]
