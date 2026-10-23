"""Labelled box-3 field extraction for ASCII Form 144 filings."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.forms.common.entities import normalize_exchange_name
from edgar_sec.engine.forms.common.numbers import format_scaled_number_string
from edgar_sec.engine.forms.common.tables import (
    clean_field_candidate,
    strip_footnote_references,
    strip_markup_tags,
)
from edgar_sec.engine.forms.form144.patterns import (
    BOX_3B_BROKER_RE,
    BOX_3B_TAIL_RE,
    BOX_3C_NEXT_LINE_RE,
    BOX_3C_TAIL_RE,
    BOX_3C_UNITS_RE,
    BOX_3D_MARKET_VALUE_RE,
    BOX_3D_TAIL_RE,
    BOX_3E_OUTSTANDING_RE,
    BOX_3F_DATE_RE,
    BOX_3G_EXCHANGE_RE,
    BOX_LABEL_LINE_RE,
)
from edgar_sec.foundation.text.dates import parse_date


@dataclass(slots=True)
class ProposedSaleRecord:
    """Parsed proposed sale record."""

    class_of_sec: str | None = None
    broker_name: str | None = None
    units_sold: str | None = None
    market_value: str | None = None
    shares_outstanding: str | None = None
    approx_sale_date: str | None = None
    exchange: str | None = None


def _forward_number(lines: list[str], idx: int) -> str | None:
    """First scaled number on the next few non-label lines."""
    for d in (1, 2, 3, 4):
        if idx + d >= len(lines):
            break
        cand = strip_markup_tags(lines[idx + d])
        if "see instr" in cand.lower() or BOX_LABEL_LINE_RE.match(cand):
            continue
        val = format_scaled_number_string(strip_footnote_references(cand))
        if val:
            return val
    return None


def _forward_date(lines: list[str], idx: int, reference_year: int | None) -> str | None:
    """First parseable date on the next few non-label lines."""
    for d in (1, 2, 3, 4):
        if idx + d >= len(lines):
            break
        cand = strip_markup_tags(lines[idx + d])
        if BOX_LABEL_LINE_RE.match(cand):
            continue
        parsed = parse_date(cand, reference_year=reference_year)
        if parsed:
            return parsed.display
    return None


def apply_box3_label(
    line: str,
    lines: list[str],
    idx: int,
    rec: ProposedSaleRecord | None,
    reference_year: int | None = None,
) -> ProposedSaleRecord | None:
    """Fill one record from a labelled box-3 line (3b through 3g)."""
    if BOX_3C_UNITS_RE.search(line):
        if rec is None:
            rec = ProposedSaleRecord()
        m_tail = BOX_3C_TAIL_RE.search(line)
        val = format_scaled_number_string(m_tail.group(1)) if m_tail else None
        if val:
            rec.units_sold = val
        else:
            for d in (1, 2, 3, 4):
                if idx + d < len(lines):
                    cand_l = strip_markup_tags(lines[idx + d])
                    if "see instr" in cand_l.lower():
                        continue
                    m_n = BOX_3C_NEXT_LINE_RE.search(cand_l)
                    val2 = format_scaled_number_string(m_n.group(1)) if m_n else None
                    if val2:
                        rec.units_sold = val2
                        break

    if BOX_3B_BROKER_RE.search(line):
        if rec is None:
            rec = ProposedSaleRecord()
        if not rec.broker_name:
            m_b = BOX_3B_TAIL_RE.search(line)
            cand = clean_field_candidate(m_b.group(1)) if m_b else None
            if cand:
                rec.broker_name = cand
            else:
                for d in (1, 2, 3):
                    if idx + d < len(lines):
                        cand = clean_field_candidate(strip_markup_tags(lines[idx + d]))
                        if (
                            not cand
                            or BOX_LABEL_LINE_RE.match(cand)
                            or cand[0].islower()
                        ):
                            continue
                        rec.broker_name = cand
                        break

    if BOX_3D_MARKET_VALUE_RE.search(line):
        if rec is None:
            rec = ProposedSaleRecord()
        m_mv = BOX_3D_TAIL_RE.search(line)
        val = format_scaled_number_string(m_mv.group(1)) if m_mv else None
        if val:
            rec.market_value = val
        elif not rec.market_value:
            rec.market_value = _forward_number(lines, idx)

    if BOX_3E_OUTSTANDING_RE.search(line):
        if rec is None:
            rec = ProposedSaleRecord()
        if not rec.shares_outstanding:
            rec.shares_outstanding = _forward_number(lines, idx)

    if BOX_3F_DATE_RE.search(line):
        if rec is None:
            rec = ProposedSaleRecord()
        if not rec.approx_sale_date:
            rec.approx_sale_date = _forward_date(lines, idx, reference_year)

    if BOX_3G_EXCHANGE_RE.search(line):
        if rec is None:
            rec = ProposedSaleRecord()
        ex = normalize_exchange_name(line)
        if ex:
            rec.exchange = ex
        elif idx + 1 < len(lines):
            ex2 = normalize_exchange_name(strip_markup_tags(lines[idx + 1]))
            if ex2:
                rec.exchange = ex2

    return rec
