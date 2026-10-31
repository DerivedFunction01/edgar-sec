"""Labelled box-3 field extraction for ASCII Form 144 filings."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.forms.common.entities import (
    is_street_or_address_line,
    normalize_exchange_name,
)
from edgar_sec.engine.forms.common.numbers import (
    NUMERIC_TOKEN_RE,
    format_scaled_number_string,
)
from edgar_sec.engine.forms.common.tables import (
    WHITESPACE_COLUMN_SPLIT_RE,
    clean_field_candidate,
    is_horizontal_rule_line,
    strip_footnote_references,
    strip_markup_tags,
)
from edgar_sec.engine.forms.form144.patterns import (
    BOX_3A_TAIL_RE,
    BOX_3A_TITLE_RE,
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
    SECURITY_CLASS_RE,
    TABLE_I_MARKER_RE,
    is_form144_instruction_line,
)
from edgar_sec.foundation.text.dates import parse_date


def _is_bare_zip_or_year(val: str, raw: str) -> bool:
    """Return True if token is an unpunctuated 5-digit ZIP or calendar year."""
    return (len(val) == 5 and not val.endswith("00") and "," not in raw) or (
        len(val) == 4 and 1990 <= int(val) <= 2030 and "," not in raw
    )


_BROKER_PROMPT_DISALLOWED = frozenset(
    {"securities", "security", "common", "class a", "class b", "preferred"}
)
_BROKER_PROMPT_PREFIXES = (
    "are to be offered",
    "acquiring the",
    "sec use only",
    "broker - dealer",
    "broker-dealer",
    "file number",
)


def _is_disallowed_broker_text(text: str) -> bool:
    low = text.lower()
    return low in _BROKER_PROMPT_DISALLOWED or low.startswith(_BROKER_PROMPT_PREFIXES)


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
    """First scaled number on the next few non-label lines, or previous line."""
    if idx > 0:
        prev = strip_markup_tags(lines[idx - 1])
        if not BOX_LABEL_LINE_RE.match(prev):
            val = format_scaled_number_string(strip_footnote_references(prev))
            if val:
                return val
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
    """First parseable date on the next few non-label lines, or previous line."""
    if idx > 0:
        prev = strip_markup_tags(lines[idx - 1])
        if not BOX_LABEL_LINE_RE.match(prev):
            parsed = parse_date(prev, reference_year=reference_year)
            if parsed:
                return parsed.display
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
        val = None
        if "see instr" not in line.lower():
            m_tail = BOX_3C_TAIL_RE.search(line)
            val = format_scaled_number_string(m_tail.group(1)) if m_tail else None
        if not val and idx > 0:
            prev = strip_markup_tags(lines[idx - 1])
            if not BOX_LABEL_LINE_RE.match(prev):
                val = format_scaled_number_string(strip_footnote_references(prev))
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
            if not cand:
                for d in (1, 2, 3, 4):
                    if idx + d < len(lines):
                        cand_f = clean_field_candidate(
                            strip_markup_tags(lines[idx + d])
                        )
                        if (
                            not cand_f
                            or BOX_LABEL_LINE_RE.match(cand_f)
                            or cand_f[0].islower()
                            or _is_disallowed_broker_text(cand_f)
                        ):
                            continue
                        cand = cand_f
                        break
            if not cand:
                for d in range(1, 6):
                    if idx - d < 0:
                        break
                    raw_prev = strip_markup_tags(lines[idx - d]).strip()
                    if not raw_prev:
                        continue
                    if BOX_LABEL_LINE_RE.match(raw_prev) or is_horizontal_rule_line(
                        raw_prev
                    ):
                        break
                    prev = clean_field_candidate(raw_prev)
                    if (
                        not prev
                        or prev[0].islower()
                        or len(prev) <= 3
                        or _is_disallowed_broker_text(prev)
                        or is_street_or_address_line(prev)
                        or _is_bare_zip_or_year(prev, prev)
                    ):
                        continue
                    cand = prev
                    break
            if cand:
                rec.broker_name = cand

    if BOX_3D_MARKET_VALUE_RE.search(line):
        if rec is None:
            rec = ProposedSaleRecord()
        val = None
        if "see instr" not in line.lower():
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
        if not ex and idx > 0:
            ex = normalize_exchange_name(strip_markup_tags(lines[idx - 1]))
        if ex:
            rec.exchange = ex
        elif idx + 1 < len(lines):
            ex2 = normalize_exchange_name(strip_markup_tags(lines[idx + 1]))
            if ex2:
                rec.exchange = ex2

    return rec


def extract_ascii_proposed_sales(
    lines: list[str],
    reference_year: int | None = None,
) -> list[ProposedSaleRecord]:
    """Extract proposed sale records across ASCII columnar, key-value, and block layouts."""
    cutoff = min(len(lines), max(40, int(len(lines) * 0.85)))

    # Step 1: Columnar Data Rows (monospace / SGML tables)
    columnar_recs: list[ProposedSaleRecord] = []
    in_b3 = False
    divider_seen = False
    pending_rec: ProposedSaleRecord | None = None
    for idx in range(cutoff):
        line = strip_markup_tags(lines[idx])
        if not line or is_form144_instruction_line(line):
            continue
        if TABLE_I_MARKER_RE.search(line):
            break
        if BOX_3A_TITLE_RE.search(line):
            in_b3 = True
        if in_b3 and is_horizontal_rule_line(line):
            divider_seen = True
            continue

        cols = [
            c.strip(" \t|")
            for c in WHITESPACE_COLUMN_SPLIT_RE.split(line)
            if c.strip(" \t|")
        ]
        if not cols:
            continue

        if (
            columnar_recs
            and not columnar_recs[-1].market_value
            and (
                cols[0].startswith("$")
                or (len(cols) >= 3 and any("$" in c for c in cols[:2]))
            )
        ):
            target = columnar_recs[-1]
            for c in cols:
                clean_c = strip_footnote_references(c)
                if not target.market_value:
                    val = format_scaled_number_string(clean_c)
                    if val and (clean_c.startswith("$") or "." in clean_c):
                        target.market_value = val
                        continue
                if not target.shares_outstanding:
                    val = format_scaled_number_string(clean_c)
                    if val and "$" not in clean_c:
                        target.shares_outstanding = val
                        continue
                if not target.approx_sale_date and parse_date(
                    clean_c, reference_year=reference_year
                ):
                    parsed_d = parse_date(clean_c, reference_year=reference_year)
                    if parsed_d:
                        target.approx_sale_date = parsed_d.display
                    continue
                if not target.exchange and normalize_exchange_name(clean_c):
                    target.exchange = normalize_exchange_name(clean_c)
                    continue
            continue

        is_sec = bool(SECURITY_CLASS_RE.search(cols[0]))
        has_num = any(
            format_scaled_number_string(strip_footnote_references(c)) for c in cols
        )

        if (
            columnar_recs
            and is_sec
            and not has_num
            and not is_form144_instruction_line(line)
            and not line.strip().startswith(("3.", "3 (", "3("))
            and len(cols[0]) < 40
        ):
            clean_sec = cols[0].strip(" \t|").partition("|")[0].strip(" \t|,:;-")
            if clean_sec and clean_sec not in (columnar_recs[-1].class_of_sec or ""):
                columnar_recs[-1].class_of_sec = (
                    f"{columnar_recs[-1].class_of_sec} {clean_sec}"
                    if columnar_recs[-1].class_of_sec
                    else clean_sec
                )
            continue

        if is_sec or (in_b3 and (divider_seen or has_num) and len(cols) >= 3):
            target_rec = (
                pending_rec
                if (pending_rec and not pending_rec.units_sold and not is_sec)
                else ProposedSaleRecord()
            )
            if is_sec:
                clean_sec = cols[0].strip(" \t|").partition("|")[0].strip(" \t|,:;-")
                target_rec.class_of_sec = " ".join(clean_sec.split())
            start_col = 1 if is_sec else 0
            for c in cols[start_col:]:
                clean_c = strip_footnote_references(c)
                if not target_rec.units_sold:
                    val = format_scaled_number_string(clean_c)
                    if (
                        val
                        and "$" not in clean_c
                        and not _is_bare_zip_or_year(val, clean_c)
                    ):
                        target_rec.units_sold = val
                        continue
                if target_rec.units_sold and not target_rec.market_value:
                    val = format_scaled_number_string(clean_c)
                    if val:
                        target_rec.market_value = val
                        continue
                if target_rec.market_value and not target_rec.shares_outstanding:
                    val = format_scaled_number_string(clean_c)
                    if (
                        val
                        and "$" not in clean_c
                        and not _is_bare_zip_or_year(val, clean_c)
                    ):
                        target_rec.shares_outstanding = val
                        continue
                if not target_rec.approx_sale_date and parse_date(
                    clean_c, reference_year=reference_year
                ):
                    parsed_d = parse_date(clean_c, reference_year=reference_year)
                    if parsed_d:
                        target_rec.approx_sale_date = parsed_d.display
                    continue
                if (
                    not target_rec.broker_name
                    and len(clean_c) > 3
                    and not clean_c[0].isdigit()
                    and not _is_disallowed_broker_text(clean_c)
                    and not is_street_or_address_line(clean_c)
                ):
                    target_rec.broker_name = clean_c
            if target_rec.units_sold:
                if target_rec not in columnar_recs:
                    columnar_recs.append(target_rec)
                pending_rec = None
            else:
                pending_rec = target_rec

    if columnar_recs:
        return columnar_recs

    # Step 2: Key-Value forward scanning
    current_rec: ProposedSaleRecord | None = None
    recs: list[ProposedSaleRecord] = []
    for idx in range(cutoff):
        line = strip_markup_tags(lines[idx])
        if not line or is_form144_instruction_line(line):
            continue
        lower = line.lower()
        if TABLE_I_MARKER_RE.search(line) or lower.startswith("instructions:"):
            break
        if lower.startswith(("see instr", "(see instr")) or "broker-dealer" in lower:
            continue

        m_3a = BOX_3A_TITLE_RE.search(line)
        if m_3a:
            if current_rec and current_rec.units_sold:
                recs.append(current_rec)
            current_rec = ProposedSaleRecord()
            m_tail = BOX_3A_TAIL_RE.search(line)
            if m_tail:
                cand = clean_field_candidate(m_tail.group(1))
                if cand and "class of" not in cand.lower():
                    cand_c = cand.strip(" \t|").partition("|")[0].strip(" \t|,:;-")
                    current_rec.class_of_sec = " ".join(cand_c.split())
            else:
                if idx > 0:
                    cand = clean_field_candidate(strip_markup_tags(lines[idx - 1]))
                    if (
                        cand
                        and len(cand) > 2
                        and "title" not in cand.lower()
                        and "class" not in cand.lower()
                    ):
                        cand_c = cand.strip(" \t|").partition("|")[0].strip(" \t|,:;-")
                        current_rec.class_of_sec = " ".join(cand_c.split())
                if not current_rec.class_of_sec and idx + 1 < len(lines):
                    cand = clean_field_candidate(strip_markup_tags(lines[idx + 1]))
                    if cand and not cand.startswith("3("):
                        cand_c = cand.strip(" \t|").partition("|")[0].strip(" \t|,:;-")
                        current_rec.class_of_sec = " ".join(cand_c.split())

        current_rec = apply_box3_label(line, lines, idx, current_rec, reference_year)

    if current_rec and current_rec.units_sold:
        recs.append(current_rec)

    if recs:
        return recs

    # Step 3: Vertical Block scanning
    for idx in range(cutoff):
        line = strip_markup_tags(lines[idx])
        if not line or is_form144_instruction_line(line):
            continue
        if TABLE_I_MARKER_RE.search(line):
            break
        if SECURITY_CLASS_RE.search(line) and len(line) < 50:
            clean_l = line.strip(" \t|").partition("|")[0].strip(" \t|,:;-")
            rec = ProposedSaleRecord(class_of_sec=" ".join(clean_l.split()))
            for d in range(1, 25):
                if idx + d >= len(lines):
                    break
                v_l = strip_markup_tags(lines[idx + d])
                if (
                    not v_l
                    or is_form144_instruction_line(v_l)
                    or is_street_or_address_line(v_l)
                ):
                    continue
                v_low = v_l.lower()
                if (
                    "instructions:" in v_low
                    or TABLE_I_MARKER_RE.search(v_l)
                    or "potential persons" in v_low
                ):
                    break
                clean_v = strip_footnote_references(v_l)
                num = format_scaled_number_string(clean_v)
                if (
                    num
                    and not rec.units_sold
                    and "$" not in clean_v
                    and not _is_bare_zip_or_year(num, clean_v)
                ):
                    rec.units_sold = num
                elif num and rec.units_sold and not rec.market_value:
                    rec.market_value = num
                elif num and rec.market_value and not rec.shares_outstanding:
                    rec.shares_outstanding = num
                else:
                    num_matches = NUMERIC_TOKEN_RE.findall(clean_v)
                    if num_matches and not rec.units_sold:
                        nums = [
                            format_scaled_number_string(m)
                            for m in num_matches
                            if format_scaled_number_string(m)
                            and not _is_bare_zip_or_year(
                                format_scaled_number_string(m), m
                            )
                        ]
                        if nums:
                            rec.units_sold = nums[0]
                            if len(nums) > 1 and not rec.market_value:
                                rec.market_value = nums[1]
                            if len(nums) > 2 and not rec.shares_outstanding:
                                rec.shares_outstanding = nums[2]
                if not rec.exchange and normalize_exchange_name(clean_v):
                    rec.exchange = normalize_exchange_name(clean_v)
                elif not rec.approx_sale_date and parse_date(
                    clean_v, reference_year=reference_year
                ):
                    parsed_d = parse_date(clean_v, reference_year=reference_year)
                    if parsed_d:
                        rec.approx_sale_date = parsed_d.display
                elif (
                    not rec.broker_name
                    and len(clean_v) > 3
                    and not clean_v[0].isdigit()
                    and not clean_v.startswith("(")
                    and not _is_disallowed_broker_text(clean_v)
                    and not is_street_or_address_line(clean_v)
                ):
                    rec.broker_name = clean_v
            if rec.units_sold:
                recs.append(rec)
                break

    return recs
