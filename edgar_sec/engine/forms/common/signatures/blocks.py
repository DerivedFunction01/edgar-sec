"""Signature candidate and block extraction from filing text."""

from __future__ import annotations

import re
from collections.abc import Sequence

from edgar_sec.domain.forms.common.signatures import Signatory, SignatureBlock
from edgar_sec.engine.document.signatures import CONFORMED_SIGNATURE_RE
from edgar_sec.engine.forms.common.signatures.names import (
    extract_clean_signatory_name,
    is_valid_signature_name,
)
from edgar_sec.engine.forms.common.signatures.patterns import (
    NOTARY_JURAT_RE,
    SIGNATURE_NAME_PATTERNS,
    SIG_NAME_RE,
    SIG_PERSON_PREFIX_RE,
    SIG_RULE_RUN_RE,
    WHITESPACE_RE,
)
from edgar_sec.foundation.text.dates import (
    ISO_DATE_RE,
    MONTH_PATTERN,
    NUMERIC_DATE_RE,
    RE_FULL_DATE,
    parse_date,
)


_TRAILING_DATE_WORD_RE = re.compile(r"\s+date\s*$", flags=re.IGNORECASE)

_TRAILING_MONTH_WORD_RE = re.compile(
    rf"\s+(?:{MONTH_PATTERN})\s*$", flags=re.IGNORECASE
)

_SURNAME_FIRST_RE = re.compile(
    r"(?i)(?:/\s*s\s*/|(?<![a-z])s/)\s*(?:by\s*:?\s*)?"
    r"([A-Z][A-Za-z\-']+,\s*[A-Z][A-Za-z\.\-']+(?:\s+[A-Z]\.)?)"
)

_LABEL_NEXT_LINE_RE = re.compile(
    r"(?im)^\s*\*{0,2}\s*signature of reporting person\s*\n\s*([^\n]{2,60}?)\s*$"
)


def extract_signature_candidate(sig_text: str) -> tuple[str | None, str | None]:
    """Extract signature name and signature date from cleaned signature block text."""
    sig_name: str | None = None
    sig_date: str | None = None
    lower = sig_text.lower()
    has_sig_rep_person = "signature of reporting person" in lower
    lines = sig_text.splitlines()

    def _first_date(text: str) -> str | None:
        unruled = SIG_RULE_RUN_RE.sub(" ", text)
        found = (
            RE_FULL_DATE.search(unruled)
            or NUMERIC_DATE_RE.search(unruled)
            or ISO_DATE_RE.search(unruled)
        )
        return found.group(0).strip() if found else None

    for line in lines:
        if CONFORMED_SIGNATURE_RE.search(line) or (
            "date" in line.lower() and len(line) < 60 and "as of" not in line.lower()
        ):
            sig_date = _first_date(line)
            if sig_date:
                break
    label_idx: int | None = None
    if has_sig_rep_person:
        label_idx = max(
            i
            for i, line in enumerate(lines)
            if "signature of reporting person" in line.lower()
        )
    if not sig_date:
        for index, line in enumerate(lines[:-1]):
            if label_idx is not None and not label_idx - 15 <= index <= label_idx + 9:
                continue
            if label_idx is None and index < len(lines) - 25:
                continue
            if not CONFORMED_SIGNATURE_RE.search(line) or _first_date(line):
                continue
            following = lines[index + 1]
            paired = _first_date(following)
            if not paired or CONFORMED_SIGNATURE_RE.search(following):
                continue
            rest = SIG_RULE_RUN_RE.sub(" ", following.replace(paired, " ")).strip(
                " ,.-\t"
            )
            if len(rest) <= 48 and not any(char.isdigit() for char in rest):
                sig_date = paired
                break
    if not sig_date and label_idx is not None:
        for line in lines[label_idx : label_idx + 9]:
            if "as of" in line.lower():
                continue
            sig_date = _first_date(line)
            if sig_date:
                break
        if not sig_date:
            for back in range(max(0, label_idx - 2), label_idx):
                found = _first_date(lines[back])
                if not found:
                    continue
                rest = lines[back].replace(found, " ").strip(" ,.-\t")
                if not rest or extract_clean_signatory_name(rest):
                    sig_date = found
                    break
    if not sig_date and not has_sig_rep_person:
        for line in lines:
            if "as of" in line.lower():
                continue
            sig_date = _first_date(line)
            if sig_date:
                break
    for pattern in SIGNATURE_NAME_PATTERNS:
        if (
            pattern is SIG_PERSON_PREFIX_RE or pattern is SIG_NAME_RE
        ) and not has_sig_rep_person:
            continue
        match = pattern.search(sig_text)
        if match:
            candidate = match.group(1).strip(" ,.-")
            candidate = _TRAILING_MONTH_WORD_RE.sub("", candidate).strip(" ,.-")
            candidate = WHITESPACE_RE.sub(" ", candidate)
            if is_valid_signature_name(candidate):
                sig_name = candidate
                break
    if sig_name is None or len(sig_name.split()) == 1:
        m_sf = _SURNAME_FIRST_RE.search(sig_text)
        if m_sf:
            cand_sf = m_sf.group(1).strip(" ,-")
            if is_valid_signature_name(cand_sf) and (
                sig_name is None or cand_sf.startswith(sig_name)
            ):
                sig_name = cand_sf
    if not sig_name and has_sig_rep_person:
        m_lbl = _LABEL_NEXT_LINE_RE.search(sig_text)
        if m_lbl:
            sig_name = extract_clean_signatory_name(m_lbl.group(1))
    if not sig_name and has_sig_rep_person:
        label_line = max(
            i
            for i, line in enumerate(lines)
            if "signature of reporting person" in line.lower()
        )
        for back in range(max(0, label_line - 3), label_line):
            prev = _TRAILING_DATE_WORD_RE.sub("", lines[back]).strip()
            if prev and SIG_RULE_RUN_RE.sub("", prev).strip():
                cleaned_prev = extract_clean_signatory_name(prev)
                if cleaned_prev:
                    sig_name = cleaned_prev
                    break
    return sig_name, sig_date


def extract_signature_block(text: str) -> SignatureBlock | None:
    """Parse text into a structured signature block with detected signatories."""
    if not text.strip():
        return None
    has_notary = bool(NOTARY_JURAT_RE.search(text))
    sig_name, sig_date = extract_signature_candidate(text)
    signatories: list[Signatory] = []
    if sig_name:
        signatories.append(Signatory(name=sig_name, date=sig_date))
    return SignatureBlock(
        signatories=tuple(signatories),
        is_conformed=bool(CONFORMED_SIGNATURE_RE.search(text)),
        has_notary=has_notary,
        raw_text=text,
    )


def find_preceding_signature_date(
    lines: Sequence[str], max_lookback: int = 10
) -> str | None:
    """Recover a signature date from the lines preceding a conformed marker."""
    for prev_line in reversed(lines[max(0, len(lines) - max_lookback) :]):
        prev_s = prev_line.strip(" \t*_=-")
        if not prev_s:
            continue
        candidate_date = extract_signature_candidate(prev_s)[1]
        if candidate_date:
            return candidate_date
        parsed = parse_date(prev_s)
        if parsed and not parsed.ambiguous:
            return prev_s
    return None


__all__ = [
    "extract_signature_block",
    "extract_signature_candidate",
    "find_preceding_signature_date",
]
