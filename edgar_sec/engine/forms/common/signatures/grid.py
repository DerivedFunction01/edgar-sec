"""Signature table classification and signature grid scanning."""

from __future__ import annotations

from collections.abc import Sequence

from edgar_sec.domain.forms.common.signatures import COMMON_SIGNATURE_LEXICAL_PACK
from edgar_sec.engine.document.signatures import CONFORMED_SIGNATURE_RE
from edgar_sec.engine.forms.common.signatures.names import (
    extract_clean_signatory_name,
)
from edgar_sec.engine.forms.common.signatures.patterns import (
    REVERSED_CONFORMED_CELL_RE,
    SIG_RULE_RUN_RE,
)
from edgar_sec.foundation.text.automaton import Token, tokenize
from edgar_sec.foundation.text.dates import (
    ISO_DATE_RE,
    MONTH_RE,
    NUMERIC_DATE_RE,
    RE_FULL_DATE,
)
from edgar_sec.foundation.text.evidence import (
    EvidenceContext,
    compile_evidence_pack,
    score_tokens,
)


_COMPILED_SIGNATURE_PACK = compile_evidence_pack(COMMON_SIGNATURE_LEXICAL_PACK)

_EVIDENCE_CTX = EvidenceContext(min_words=1)


def is_signature_table(
    lower: str,
    past_tables: bool,
    *,
    extra_markers: tuple[str, ...] = (),
    tokens: Sequence[Token] | None = None,
) -> bool:
    """Classify whether table text represents a conformed signature section."""
    if not past_tables and not any(
        k in lower
        for k in (
            "signature",
            "misstatement",
            "criminal",
            "presents",
            "attorney",
            "notary",
            "sworn",
            "signatory",
            "yours",
        )
    ):
        return False
    resolved = tokens if tokens is not None else tokenize(lower)
    score = score_tokens(resolved, _COMPILED_SIGNATURE_PACK, _EVIDENCE_CTX)
    if "signature_decisive" in score.satisfied_tiers and not score.exclusions:
        return True
    if not past_tables:
        return False
    if any(marker in lower for marker in ("/s/", "-s-", "signature:", *extra_markers)):
        return True
    if (
        len(lower) < 80
        and ("date" in lower or "dated" in lower)
        and bool(NUMERIC_DATE_RE.search(lower) or MONTH_RE.search(lower))
    ):
        return True
    return score.score >= 2 and not score.exclusions


def _name_from_cell(cell: str) -> str | None:
    cand = extract_clean_signatory_name(cell)
    if cand is None and "\n" in cell:
        cand = extract_clean_signatory_name(" ".join(cell.split()))
    if cand is None:
        matches = list(CONFORMED_SIGNATURE_RE.finditer(cell))
        if matches:
            cand = extract_clean_signatory_name(cell[matches[-1].start() :])
    return cand


def scan_signature_grid(
    rows: tuple[tuple[str, ...], ...] | list[tuple[str, ...]],
    *,
    strict_dates: bool = False,
) -> tuple[str | None, str | None]:
    """Scan 2D grid rows to extract clean signatory name and date."""
    sig_name: str | None = None
    sig_date: str | None = None
    for r_idx, row in enumerate(rows):
        r_str = " ".join(row).lower()
        row_is_signature = any(
            marker in r_str for marker in ("signature", "/s/", "-s-")
        ) or any(REVERSED_CONFORMED_CELL_RE.match(cell) for cell in row)
        if not sig_name and row_is_signature:
            for cell in row:
                cand = _name_from_cell(cell)
                if cand:
                    sig_name = cand
                    break
            if not sig_name and r_idx + 1 < len(rows):
                for cell in rows[r_idx + 1]:
                    cand = _name_from_cell(cell)
                    if cand:
                        sig_name = cand
                        break
            if not sig_name and r_idx > 0:
                for cell in rows[r_idx - 1]:
                    cand = _name_from_cell(cell)
                    if cand:
                        sig_name = cand
                        break

        date_marker = any(marker in r_str for marker in ("date", "notice"))
        if not sig_date and (row_is_signature or (date_marker and not strict_dates)):
            for cell in row:
                if not date_marker and len(cell.strip()) > 40:
                    continue
                m_date = (
                    RE_FULL_DATE.search(cell)
                    or NUMERIC_DATE_RE.search(cell)
                    or ISO_DATE_RE.search(cell)
                )
                if m_date and "as of" not in cell.lower():
                    sig_date = m_date.group(0).strip()
                    break
            if not sig_date and row_is_signature:
                for cell in row:
                    if "/s/" not in cell.lower() and "-s-" not in cell.lower():
                        continue
                    unruled = SIG_RULE_RUN_RE.sub(" ", cell)
                    m_date = (
                        RE_FULL_DATE.search(unruled)
                        or NUMERIC_DATE_RE.search(unruled)
                        or ISO_DATE_RE.search(unruled)
                    )
                    if m_date and "as of" not in cell.lower():
                        sig_date = m_date.group(0).strip()
                        break
        if sig_name and sig_date:
            break
    return sig_name, sig_date


__all__ = [
    "is_signature_table",
    "scan_signature_grid",
]
