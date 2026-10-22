"""Columnar (fixed-width) signature and notice-date extraction."""

from __future__ import annotations

import re
from collections.abc import Sequence

from edgar_sec.engine.forms.common.signatures import extract_clean_signatory_name

_SIGNATURE_LINE_RE = re.compile(
    r"(?:/s/|signature:)\s*(?:/s/\s*)?([A-Za-z\.\,\s\-]+)", re.IGNORECASE
)
_STRIP_SLASH_S_RE = re.compile(r"^.*?/s/\s*")
_WHITESPACE_SPLIT_RE = re.compile(r"\t+|\s{2,}")


def extract_columnar_signature_and_date(
    lines: Sequence[str],
    *,
    start_idx: int = 0,
    reference_year: int | None = None,
) -> tuple[str | None, str | None]:
    """Scan trailing lines backward for conformed signature and notice date."""
    from edgar_sec.engine.forms.common.tables import (
        is_horizontal_rule_line,
        strip_markup_tags,
    )
    from edgar_sec.foundation.text.dates import parse_date

    sig_name: str | None = None
    sig_date: str | None = None
    total_lines = len(lines)

    for idx in range(total_lines - 1, start_idx - 1, -1):
        line = strip_markup_tags(lines[idx])
        if not line or is_horizontal_rule_line(line):
            continue
        lower = line.lower()
        if (
            "intentional misstatements" in lower
            or "criminal violations" in lower
            or "sec 1147" in lower
        ):
            continue

        if not sig_name and ("/s/" in line or "signature:" in lower):
            m = _SIGNATURE_LINE_RE.search(line)
            if m:
                cand = extract_clean_signatory_name(m.group(1))
                if cand:
                    sig_name = cand

        if not sig_name and ("(signature)" in lower or lower == "signature"):
            for d in range(1, 5):
                if idx - d >= 0:
                    above_l = strip_markup_tags(lines[idx - d])
                    if (
                        above_l
                        and not is_horizontal_rule_line(above_l)
                        and not above_l.lower().startswith("date")
                    ):
                        cols = [
                            c.strip()
                            for c in _WHITESPACE_SPLIT_RE.split(above_l)
                            if c.strip()
                        ]
                        for c in reversed(cols):
                            clean_c = _STRIP_SLASH_S_RE.sub("", c) if "/s/" in c else c
                            cand = extract_clean_signatory_name(clean_c)
                            if cand and not any(
                                k in cand.lower()
                                for k in ("attention:", "signature", "notice", "date")
                            ):
                                sig_name = cand
                                break
                        if sig_name:
                            if not sig_date and len(cols) > 1:
                                parsed = parse_date(
                                    cols[0], reference_year=reference_year
                                )
                                if parsed:
                                    sig_date = parsed.display
                            break

        if not sig_date and ("date of notice" in lower or lower.startswith("date:")):
            p_d = parse_date(line, reference_year=reference_year)
            if p_d and "as of" not in lower:
                sig_date = p_d.display
            else:
                for d in (-2, -1, 1, 2):
                    if 0 <= idx + d < total_lines:
                        adj_l = strip_markup_tags(lines[idx + d])
                        p_adj = parse_date(adj_l, reference_year=reference_year)
                        if p_adj and "as of" not in adj_l.lower():
                            sig_date = p_adj.display
                            break

    return sig_name, sig_date


__all__ = ["extract_columnar_signature_and_date"]
