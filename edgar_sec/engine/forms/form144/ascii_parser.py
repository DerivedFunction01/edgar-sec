"""ASCII and SGML state machine parser for Form 144 filings."""

from __future__ import annotations

from dataclasses import dataclass, field

from edgar_sec.engine.forms.common.entities import (
    IRS_RE,
    is_street_or_address_line,
    normalize_exchange_name,
)
from edgar_sec.engine.forms.common.numbers import format_scaled_number_string
from edgar_sec.engine.forms.common.columnar_signatures import (
    extract_columnar_signature_and_date,
)
from edgar_sec.engine.forms.common.tables import (
    WHITESPACE_COLUMN_SPLIT_RE,
    clean_field_candidate,
    is_horizontal_rule_line,
    strip_footnote_references,
    strip_markup_tags,
)
from edgar_sec.engine.forms.form144.healing import heal_form144_lines
from edgar_sec.engine.forms.form144.patterns import (
    BOX_1A_LABEL_RE,
    BOX_1A_TAIL_RE,
    BOX_1B_IRS_LABEL_RE,
    BOX_1C_SEC_LABEL_RE,
    BOX_2A_LABEL_RE,
    BOX_2A_TAIL_RE,
    BOX_3A_TAIL_RE,
    BOX_3A_TITLE_RE,
    BOX_3C_NEXT_LINE_RE,
    BOX_3C_TAIL_RE,
    BOX_3C_UNITS_RE,
    BOX_3D_MARKET_VALUE_RE,
    BOX_3D_TAIL_RE,
    BOX_3G_EXCHANGE_RE,
    NUMERIC_TOKEN_RE,
    RELATIONSHIP_LABEL_RE,
    RELATIONSHIP_TAIL_RE,
    SEC_FILE_BARE_RE,
    SEC_FILE_LABEL_RE,
    SECURITY_CLASS_RE,
    is_cover_header_or_subbox_line,
    is_form144_instruction_line,
)
from edgar_sec.engine.tables.ascii_html.model import ResolvedGrid
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


@dataclass(slots=True)
class Form144AsciiSlots:
    """State machine slots for Form 144 ASCII filings."""

    issuer_name: str | None = None
    issuer_irs: str | None = None
    issuer_sec_no: str | None = None
    issuer_address: str | None = None
    issuer_phone: str | None = None
    reporting_person: str | None = None
    relationship: str | None = None
    filer_address: str | None = None
    proposed_sales: list[ProposedSaleRecord] = field(default_factory=list)
    sig_name: str | None = None
    sig_date: str | None = None


def _extract_cover_fields(lines: list[str], slots: Form144AsciiSlots) -> None:
    cutoff = min(len(lines), max(30, int(len(lines) * 0.7)))
    for idx in range(cutoff):
        line = strip_markup_tags(lines[idx])
        if not line or is_form144_instruction_line(line):
            continue
        lower = line.lower()

        # 1(a) NAME OF ISSUER
        if not slots.issuer_name and BOX_1A_LABEL_RE.search(line) and "issuer" in lower:
            m_tail = BOX_1A_TAIL_RE.search(line)
            cand = clean_field_candidate(m_tail.group(1)) if m_tail else None
            if cand and len(cand) > 2 and not is_cover_header_or_subbox_line(cand):
                slots.issuer_name = cand
            else:
                for d in range(1, 10):
                    if idx + d < len(lines):
                        cand_l = strip_markup_tags(lines[idx + d])
                        if (
                            cand_l
                            and not is_horizontal_rule_line(cand_l)
                            and not is_form144_instruction_line(cand_l)
                        ):
                            if ":" in cand_l:
                                _, _, val_part = cand_l.partition(":")
                                cand = clean_field_candidate(val_part.strip())
                                if (
                                    cand
                                    and len(cand) > 2
                                    and not is_cover_header_or_subbox_line(cand)
                                ):
                                    slots.issuer_name = cand
                                    break
                            cols = [
                                c.strip()
                                for c in WHITESPACE_COLUMN_SPLIT_RE.split(cand_l)
                                if c.strip()
                            ]
                            if not cols:
                                continue
                            first_col = clean_field_candidate(cols[0])
                            if (
                                first_col
                                and len(first_col) > 2
                                and not is_cover_header_or_subbox_line(first_col)
                            ):
                                slots.issuer_name = first_col
                                if len(cols) > 1 and IRS_RE.search(cols[1]):
                                    slots.issuer_irs = IRS_RE.search(cols[1]).group(0)
                                if len(cols) > 2 and SEC_FILE_BARE_RE.search(cols[2]):
                                    slots.issuer_sec_no = SEC_FILE_BARE_RE.search(
                                        cols[2]
                                    ).group(0)
                                break

        # 1(b) IRS ID
        if not slots.issuer_irs and BOX_1B_IRS_LABEL_RE.search(line):
            m_irs = IRS_RE.search(line)
            if m_irs:
                slots.issuer_irs = m_irs.group(0)
            elif idx + 1 < len(lines):
                m_irs = IRS_RE.search(lines[idx + 1])
                if m_irs:
                    slots.issuer_irs = m_irs.group(0)

        # 1(c) SEC FILE NO
        if not slots.issuer_sec_no and BOX_1C_SEC_LABEL_RE.search(line):
            m_sec = SEC_FILE_LABEL_RE.search(line) or SEC_FILE_BARE_RE.search(line)
            if m_sec:
                slots.issuer_sec_no = m_sec.group(1)

        # 2(a) NAME OF PERSON
        if not slots.reporting_person and BOX_2A_LABEL_RE.search(line):
            m_tail = BOX_2A_TAIL_RE.search(line)
            cand = clean_field_candidate(m_tail.group(1)) if m_tail else None
            if (
                cand
                and len(cand) > 2
                and not is_cover_header_or_subbox_line(cand)
                and not cand[0].isdigit()
                and not cand.startswith("%")
            ):
                slots.reporting_person = cand
            else:
                for d in range(1, 10):
                    if idx + d < len(lines):
                        cand_l = strip_markup_tags(lines[idx + d])
                        if (
                            cand_l
                            and not is_horizontal_rule_line(cand_l)
                            and not is_form144_instruction_line(cand_l)
                        ):
                            if ":" in cand_l:
                                _, _, val_part = cand_l.partition(":")
                                cand = clean_field_candidate(val_part.strip())
                                if (
                                    cand
                                    and len(cand) > 2
                                    and not is_cover_header_or_subbox_line(cand)
                                    and not cand[0].isdigit()
                                    and not cand.startswith("%")
                                ):
                                    slots.reporting_person = cand
                                    break
                            cols = [
                                c.strip()
                                for c in WHITESPACE_COLUMN_SPLIT_RE.split(cand_l)
                                if c.strip()
                            ]
                            if not cols:
                                continue
                            first_col = clean_field_candidate(cols[0])
                            if (
                                first_col
                                and len(first_col) > 2
                                and not is_cover_header_or_subbox_line(first_col)
                                and not first_col[0].isdigit()
                                and not first_col.startswith("%")
                            ):
                                slots.reporting_person = first_col
                                if not slots.relationship and len(cols) > 2:
                                    rel_cand = clean_field_candidate(cols[2])
                                    if (
                                        rel_cand
                                        and len(rel_cand) > 1
                                        and not rel_cand[0].isdigit()
                                    ):
                                        slots.relationship = rel_cand
                                break

        # 2(b) or 2(c) RELATIONSHIP
        if not slots.relationship and RELATIONSHIP_LABEL_RE.search(line):
            m_rel = RELATIONSHIP_TAIL_RE.search(line)
            cand = clean_field_candidate(m_rel.group(1)) if m_rel else None
            if cand and len(cand) > 1:
                slots.relationship = cand
            elif idx + 1 < len(lines):
                next_l = strip_markup_tags(lines[idx + 1])
                cand = clean_field_candidate(next_l)
                if cand and len(cand) > 1 and not cand.startswith("2("):
                    slots.relationship = cand


def _extract_proposed_sales(
    lines: list[str],
    slots: Form144AsciiSlots,
    full_text: str,
    reference_year: int | None = None,
) -> None:
    cutoff = min(len(lines), max(40, int(len(lines) * 0.85)))

    # Step 1: Scan for Columnar Data Rows (e.g. SGML or monospace tables)
    columnar_recs: list[ProposedSaleRecord] = []
    in_b3 = False
    divider_seen = False
    pending_rec: ProposedSaleRecord | None = None
    for idx in range(cutoff):
        line = strip_markup_tags(lines[idx])
        if not line or is_form144_instruction_line(line):
            continue
        lower = line.lower()
        if "table i" in lower or "table 1" in lower:
            break
        if "3(a)" in lower or "3 (a)" in lower or "3. (a)" in lower:
            in_b3 = True
        if in_b3 and is_horizontal_rule_line(line):
            divider_seen = True
            continue

        cols = [c.strip() for c in WHITESPACE_COLUMN_SPLIT_RE.split(line) if c.strip()]
        if not cols:
            continue
        is_sec = bool(SECURITY_CLASS_RE.search(cols[0]))
        has_num = any(
            format_scaled_number_string(strip_footnote_references(c)) for c in cols
        )
        if is_sec or (in_b3 and (divider_seen or has_num) and len(cols) >= 3):
            target_rec = (
                pending_rec
                if (pending_rec and not pending_rec.units_sold and not is_sec)
                else ProposedSaleRecord()
            )
            if is_sec:
                target_rec.class_of_sec = cols[0]
            start_col = 1 if is_sec else 0
            for c in cols[start_col:]:
                clean_c = strip_footnote_references(c)
                if not target_rec.units_sold:
                    val = format_scaled_number_string(clean_c)
                    if val and "$" not in clean_c:
                        target_rec.units_sold = val
                        continue
                if target_rec.units_sold and not target_rec.market_value:
                    val = format_scaled_number_string(clean_c)
                    if val:
                        target_rec.market_value = val
                        continue
                if not target_rec.exchange and normalize_exchange_name(clean_c):
                    target_rec.exchange = normalize_exchange_name(clean_c)
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
                ):
                    target_rec.broker_name = clean_c
            if target_rec.units_sold:
                if target_rec not in columnar_recs:
                    columnar_recs.append(target_rec)
                pending_rec = None
            else:
                pending_rec = target_rec

    if columnar_recs:
        slots.proposed_sales.extend(columnar_recs)
        return

    # Step 2: Key-Value forward scanning
    current_rec: ProposedSaleRecord | None = None
    for idx in range(cutoff):
        line = strip_markup_tags(lines[idx])
        if not line or is_form144_instruction_line(line):
            continue
        lower = line.lower()
        if "table i" in lower or "table 1" in lower or "instructions:" in lower:
            break
        if "see instr" in lower or "broker-dealer" in lower:
            continue

        # Check for 3(a) Anchor
        m_3a = BOX_3A_TITLE_RE.search(line)
        if m_3a:
            if current_rec and current_rec.units_sold:
                slots.proposed_sales.append(current_rec)
            current_rec = ProposedSaleRecord()
            m_tail = BOX_3A_TAIL_RE.search(line)
            if m_tail:
                cand = clean_field_candidate(m_tail.group(1))
                if cand and "class of" not in cand.lower():
                    current_rec.class_of_sec = cand
            else:
                tail = BOX_3A_TITLE_RE.sub("", line).strip()
                cand = clean_field_candidate(tail)
                if (
                    cand
                    and len(cand) > 2
                    and "title" not in cand.lower()
                    and "class" not in cand.lower()
                ):
                    current_rec.class_of_sec = cand
                elif idx + 1 < len(lines):
                    cand = clean_field_candidate(strip_markup_tags(lines[idx + 1]))
                    if cand and not cand.startswith("3("):
                        current_rec.class_of_sec = cand

        # Check for 3(c) Units to be sold
        if BOX_3C_UNITS_RE.search(line):
            if current_rec is None:
                current_rec = ProposedSaleRecord()
            m_tail = BOX_3C_TAIL_RE.search(line)
            val = format_scaled_number_string(m_tail.group(1)) if m_tail else None
            if val:
                current_rec.units_sold = val
            else:
                for d in (1, 2, 3, 4):
                    if idx + d < len(lines):
                        cand_l = strip_markup_tags(lines[idx + d])
                        if "see instr" in cand_l.lower():
                            continue
                        m_n = BOX_3C_NEXT_LINE_RE.search(cand_l)
                        val2 = (
                            format_scaled_number_string(m_n.group(1)) if m_n else None
                        )
                        if val2:
                            current_rec.units_sold = val2
                            break

        # Check for 3(d) Market Value
        if BOX_3D_MARKET_VALUE_RE.search(line):
            if current_rec is None:
                current_rec = ProposedSaleRecord()
            m_mv = BOX_3D_TAIL_RE.search(line)
            val = format_scaled_number_string(m_mv.group(1)) if m_mv else None
            if val:
                current_rec.market_value = val

        # Check for 3(g) Exchange
        if BOX_3G_EXCHANGE_RE.search(line):
            if current_rec is None:
                current_rec = ProposedSaleRecord()
            ex = normalize_exchange_name(line)
            if ex:
                current_rec.exchange = ex
            elif idx + 1 < len(lines):
                ex2 = normalize_exchange_name(strip_markup_tags(lines[idx + 1]))
                if ex2:
                    current_rec.exchange = ex2

    if current_rec and current_rec.units_sold:
        slots.proposed_sales.append(current_rec)

    # Step 3: Vertical Block scanning
    if not slots.proposed_sales:
        for idx in range(cutoff):
            line = strip_markup_tags(lines[idx])
            if not line or is_form144_instruction_line(line):
                continue
            lower = line.lower()
            if "table i" in lower or "table 1" in lower:
                break
            if SECURITY_CLASS_RE.search(line) and len(line) < 50:
                rec = ProposedSaleRecord(class_of_sec=line)
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
                        or "table i" in v_low
                        or "table 1" in v_low
                        or "potential persons" in v_low
                    ):
                        break
                    clean_v = strip_footnote_references(v_l)
                    num = format_scaled_number_string(clean_v)
                    if num and not rec.units_sold and "$" not in clean_v:
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
                    ):
                        rec.broker_name = clean_v
                if rec.units_sold:
                    slots.proposed_sales.append(rec)
                    break


def _build_grids(
    slots: Form144AsciiSlots,
) -> tuple[ResolvedGrid, ResolvedGrid, ResolvedGrid]:
    cover_rows = (
        ("1(a) NAME OF ISSUER", slots.issuer_name or ""),
        (
            "1(b) IRS IDENT. NO.",
            slots.issuer_irs or "",
            "(c) S.E.C. FILE NO.",
            slots.issuer_sec_no or "",
        ),
        (
            "2(a) NAME OF PERSON FOR WHOSE ACCOUNT THE SECURITIES ARE TO BE SOLD",
            slots.reporting_person or "",
        ),
        ("(c) RELATIONSHIP TO ISSUER", slots.relationship or ""),
    )
    cover_grid = ResolvedGrid(
        rows=cover_rows, column_alignments=(), column_widths=(), confidence=1.0
    )

    header = (
        "3(a) Title of Class",
        "3(b) Broker",
        "3(c) Number of Shares",
        "3(d) Aggregate Market Value",
        "3(e) Outstanding",
        "3(f) Date of Sale",
        "3(g) Exchange",
    )
    b3_rows: list[tuple[str, ...]] = [header]
    for sale in slots.proposed_sales:
        b3_rows.append(
            (
                sale.class_of_sec or "",
                sale.broker_name or "",
                sale.units_sold or "",
                sale.market_value or "",
                sale.shares_outstanding or "",
                sale.approx_sale_date or "",
                sale.exchange or "",
            )
        )
    b3_grid = ResolvedGrid(
        rows=tuple(b3_rows),
        column_alignments=(),
        column_widths=(),
        confidence=1.0,
    )

    sig_rows = (
        (
            slots.sig_date or "",
            f"/s/ {slots.sig_name}" if slots.sig_name else "",
        ),
        ("(DATE OF NOTICE)", "(SIGNATURE)"),
    )
    sig_grid = ResolvedGrid(
        rows=sig_rows, column_alignments=(), column_widths=(), confidence=1.0
    )

    return cover_grid, b3_grid, sig_grid


def parse_ascii_form144(
    raw_text: str, reference_year: int | None = None
) -> Form144Sections | None:
    """Parse Form 144 from ASCII / SGML / PRE text into Form144Sections."""
    from edgar_sec.engine.forms.form144.sections import (
        ClassifiedSection,
        Form144Sections,
        SectionRole,
    )

    raw_lines = raw_text.splitlines()
    if not raw_lines:
        return None

    # Apply Form 144 sentence instruction healing, phrase healing, and date repairs
    lines = heal_form144_lines(raw_lines)

    slots = Form144AsciiSlots()
    total_lines = len(lines)
    start_sig_idx = max(0, int(total_lines * 0.45))

    sig_name, sig_date = extract_columnar_signature_and_date(
        lines, start_idx=start_sig_idx, reference_year=reference_year
    )
    slots.sig_name = sig_name
    slots.sig_date = sig_date

    _extract_cover_fields(lines, slots)
    _extract_proposed_sales(lines, slots, raw_text, reference_year)

    # Require at least issuer_name or reporting_person to consider it a Form 144
    if not slots.issuer_name and not slots.reporting_person:
        return None

    cover_grid, b3_grid, sig_grid = _build_grids(slots)

    cover_sec = ClassifiedSection(
        role=SectionRole.COVER_BOX_1_2,
        table_index=0,
        raw_node=None,
        resolved_grid=cover_grid,
    )
    b3_sec = ClassifiedSection(
        role=SectionRole.PROPOSED_SALE_BOX_3,
        table_index=1,
        raw_node=None,
        resolved_grid=b3_grid,
    )
    sig_sec = ClassifiedSection(
        role=SectionRole.SIGNATURES,
        table_index=2,
        raw_node=None,
        resolved_grid=sig_grid,
    )

    return Form144Sections(
        cover_box_1_2=cover_sec,
        proposed_sale_box_3=b3_sec,
        table_i=None,
        table_ii=None,
        signatures=[sig_sec],
        remarks=[],
        unparsed=[],
    )


__all__ = [
    "Form144AsciiSlots",
    "ProposedSaleRecord",
    "parse_ascii_form144",
]
