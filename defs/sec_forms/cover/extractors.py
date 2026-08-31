"""Universal cover-page extractors operating on normalized text."""

from __future__ import annotations

import re

from defs.entities import clean_entity_name, entity_name_tokens
from defs.regex import build_alternation
from defs.sec_forms.cover.vocabulary import (
    COMMISSION_FILE_RE,
    EIN_VALUE_RE,
    IRS_EIN_RE,
)
from defs.text.dates import YEAR_IN_TEXT_RE, parse_date

_FISCAL_ANCHOR_TERMS = ("fiscal", "period", "year")
_FISCAL_END_TERMS = ("end", "ended", "ending")


def clean_company_name_string(raw: str) -> str:
    """Strip jurisdiction codes (e.g. /DE/, /WA) and trailing legal punctuation."""
    return clean_entity_name(raw)


def get_core_name_tokens(name: str) -> list[str]:
    """Extract lowercased core stem tokens stripping legal suffixes and stopwords."""
    return entity_name_tokens(name)


def match_company_name(
    candidate_text: str,
    target_name: str,
    former_names: list[str] | None = None,
) -> tuple[bool, str, float]:
    """Hierarchical 5-tier company name matcher."""
    if not candidate_text or not target_name:
        return False, "none", 0.0

    all_targets = [target_name] + (former_names or [])
    cand_cleaned = clean_company_name_string(candidate_text).lower()
    cand_tokens = re.findall(r"[a-z0-9]+", cand_cleaned)
    cand_norm = " ".join(cand_tokens)
    cand_core = get_core_name_tokens(candidate_text)
    cand_core_set = set(cand_core)

    # Tier 1: Exact Normalized Full Match
    for target in all_targets:
        target_tokens = re.findall(
            r"[a-z0-9]+", clean_company_name_string(target).lower()
        )
        target_norm = " ".join(target_tokens)
        if cand_norm == target_norm and cand_norm:
            return True, "Tier 1: Exact Full Match", 1.0

    # Tier 2: Core Stem / Family Match
    for target in all_targets:
        target_core = get_core_name_tokens(target)
        if target_core and (
            cand_core == target_core or cand_core_set == set(target_core)
        ):
            return True, "Tier 2: Core Family Match", 0.95

    # Tier 3: Substring / Subset Match
    for target in all_targets:
        target_core_set = set(get_core_name_tokens(target))
        if target_core_set and target_core_set.issubset(cand_core_set):
            return True, "Tier 3: Substring Match", 0.85
        if (
            cand_core_set
            and cand_core_set.issubset(target_core_set)
            and any(len(w) >= 4 for w in cand_core_set)
        ):
            return True, "Tier 3: Substring Match", 0.82

    # Tier 4: Jaccard Overlap >= 0.50
    for target in all_targets:
        target_core_set = set(get_core_name_tokens(target))
        if target_core_set and cand_core_set:
            overlap = len(target_core_set.intersection(cand_core_set))
            union = len(target_core_set.union(cand_core_set))
            if union > 0 and (overlap / union) >= 0.50:
                return True, "Tier 4: Jaccard Overlap Match", 0.70

    return False, "none", 0.0


def normalize_ein(candidate: str | None) -> str | None:
    """Strictly normalize a candidate sequence into a 9-digit IRS EIN (XX-XXXXXXX)."""
    if not candidate:
        return None
    digits = re.sub(r"\D", "", str(candidate))
    if len(digits) == 9 and not digits.startswith("0000"):
        return f"{digits[:2]}-{digits[2:]}"
    return None


def extract_candidate_ein(text: str, default_ein: str | None = None) -> str | None:
    """Find and normalize IRS EIN from a text snippet."""
    m_dashed = EIN_VALUE_RE.search(text)
    if m_dashed:
        ein = normalize_ein(m_dashed.group(0))
        if ein:
            return ein

    label_match = IRS_EIN_RE.search(text)
    if label_match:
        nearby = text[label_match.end() : label_match.end() + 40]
        m_val = EIN_VALUE_RE.search(nearby)
        if m_val:
            ein = normalize_ein(m_val.group(0))
            if ein:
                return ein

    return normalize_ein(default_ein)


def extract_fiscal_period(
    soup_or_text: str,
    filing_year: int | None = None,
    default_fy: str | None = None,
) -> str | None:
    """Extract fiscal year or quarterly period end date handling horizontal, vertical, and standalone years."""
    raw_str = str(soup_or_text)

    anchor_m = re.search(
        rf"(?i)\b(?:{build_alternation(_FISCAL_ANCHOR_TERMS)})\b[\s\w<>/\"\'\=\:\;\-–—]{{0,50}}?\b(?:{build_alternation(_FISCAL_END_TERMS)})\b",
        raw_str,
    )
    if anchor_m:
        lookahead = raw_str[anchor_m.end() : anchor_m.end() + 250]
        clean_lookahead = " ".join(re.sub(r"<[^>]*>", " ", lookahead).split())

        parsed = parse_date(clean_lookahead)
        if parsed is not None:
            cand_date = parsed.source
            if filing_year:
                if abs(parsed.components.year - filing_year) <= 1:
                    return cand_date
            else:
                return cand_date

        m_year = YEAR_IN_TEXT_RE.search(clean_lookahead)
        if m_year:
            cand_year = m_year.group(1)
            if not filing_year or abs(int(cand_year) - filing_year) <= 1:
                return cand_year

    return default_fy


def extract_commission_file_number(
    text_snippet: str,
    default_file: str | None = None,
) -> str | None:
    """Extract SEC commission file number."""
    m = re.search(
        rf"(?i)(?:{COMMISSION_FILE_RE.pattern})[\s\:\.\-\–—<>\w\/]{{0,30}}(\d{{1,3}}[\-\s]\d{{3,8}}(?:[\-\s]\d{{2,4}})?)",
        text_snippet,
    )
    if m:
        return m.group(1).strip()
    return default_file


__all__ = [
    "clean_company_name_string",
    "extract_candidate_ein",
    "extract_commission_file_number",
    "extract_fiscal_period",
    "get_core_name_tokens",
    "match_company_name",
    "normalize_ein",
]
