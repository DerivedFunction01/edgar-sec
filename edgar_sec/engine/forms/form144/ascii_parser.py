"""ASCII and SGML state machine parser for Form 144 filings."""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from edgar_sec.engine.forms.common.entities import (
    IRS_RE,
    is_street_or_address_line,
    normalize_exchange_name,
)
from edgar_sec.engine.forms.common.numbers import (
    NUMERIC_TOKEN_RE,
    format_scaled_number_string,
)
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
from edgar_sec.engine.forms.form144.ascii_scan import (
    ProposedSaleRecord,
    apply_box3_label,
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
    PHONE_RE,
    RELATIONSHIP_LABEL_RE,
    RELATIONSHIP_TAIL_RE,
    SEC_FILE_BARE_RE,
    SEC_FILE_LABEL_RE,
    SECURITY_CLASS_RE,
    TABLE_I_MARKER_RE,
    is_cover_header_or_subbox_line,
    is_form144_instruction_line,
)
from edgar_sec.engine.tables.ascii_html.model import ResolvedGrid
from edgar_sec.foundation.text.dates import parse_date

_SUBBOX_LINE_RE = re.compile(r"^\s*(?:\d\s*)?\([a-e]\)")
_TABLE_I_HEADING_RE = re.compile(r"^\s*table\s+i\b(?!i)", re.IGNORECASE)
_TABLE_II_HEADING_RE = re.compile(r"^\s*table\s+ii\b", re.IGNORECASE)
_REMARKS_HEADING_RE = re.compile(r"^\s*remarks\b", re.IGNORECASE)

_TABLE_I_LABELS = (
    ("title of the class", "class_title", "Title of the Class"),
    ("date you acquired", "acquired_date", "Date You Acquired"),
    ("nature of acquisition", "nature_of_acquisition", "Nature of Acquisition"),
    (
        "name of person from whom acquired",
        "donor_or_seller_name",
        "Name of Person from Whom Acquired",
    ),
    ("amount of securities acquired", "amount_acquired", "Amount Acquired"),
    ("date of payment", "payment_date", "Date of Payment"),
    ("nature of payment", "nature_of_payment", "Nature of Payment"),
)
_TABLE_II_LABELS = (
    ("name and address of seller", "seller_name", "Name and Address of Seller"),
    ("title of securities sold", "class_title", "Title of Securities Sold"),
    ("date of sale", "sale_date", "Date of Sale"),
    ("amount of securities sold", "amount_sold", "Amount of Securities Sold"),
    ("gross proceeds", "gross_proceeds", "Gross Proceeds"),
)


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
    table_i_values: dict[str, str] = field(default_factory=dict)
    table_ii_values: dict[str, str] = field(default_factory=dict)
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

        # 1(d) ADDRESS OF ISSUER
        if not slots.issuer_address and "address of issuer" in lower:
            slots.issuer_address = _following_value(lines, idx, line)

        # 1(e) TELEPHONE NO.
        if not slots.issuer_phone and "telephone" in lower:
            m_phone = PHONE_RE.search(line)
            if m_phone:
                slots.issuer_phone = m_phone.group(0)

        # 2(c) ADDRESS OF PERSON
        if (
            not slots.filer_address
            and "(c)" in lower
            and "address" in lower
            and "issuer" not in lower
        ):
            slots.filer_address = _following_value(lines, idx, line)


def _following_value(lines: list[str], idx: int, line: str) -> str | None:
    tail = line.partition(":")[2].strip()
    if tail and len(tail) > 3:
        return clean_field_candidate(tail)
    parts: list[str] = []
    for d in range(1, 5):
        if idx + d >= len(lines):
            break
        cand = strip_markup_tags(lines[idx + d])
        if (
            not cand
            or is_horizontal_rule_line(cand)
            or is_form144_instruction_line(cand)
            or _SUBBOX_LINE_RE.match(cand.lower())
        ):
            if parts:
                break
            continue
        parts.append(cand.strip())
        if len(parts) >= 3:
            break
    return clean_field_candidate(" ".join(parts)) if parts else None


def _labelled_region_values(
    lines: list[str],
    start: int,
    stop_res: tuple[re.Pattern[str], ...],
    labels: tuple[tuple[str, str, str], ...],
) -> dict[str, str]:
    values: dict[str, str] = {}
    pending: str | None = None
    idx = start
    while idx < len(lines):
        line = strip_markup_tags(lines[idx])
        idx += 1
        if any(rx.search(line) for rx in stop_res):
            break
        if not line.strip() or is_form144_instruction_line(line):
            continue
        lower = line.lower()
        matched = next((key for label, key, _h in labels if label in lower), None)
        if matched is not None:
            pending = None
            if matched not in values:
                tail = line.partition(":")[2].strip() if ":" in line else ""
                if tail:
                    values[matched] = tail
                else:
                    pending = matched
            continue
        if pending is not None:
            tail = line.partition(":")[2].strip() if ":" in line else line.strip()
            if tail:
                values[pending] = tail
            pending = None
            continue
        if "seller_name" in values and "class_title" not in values:
            values["seller_name"] += "\n" + line.strip()
    return values


def _extract_ascii_tables(lines: list[str], slots: Form144AsciiSlots) -> None:
    table_i_start = next(
        (i for i, raw in enumerate(lines) if _TABLE_I_HEADING_RE.search(raw)),
        None,
    )
    if table_i_start is not None:
        slots.table_i_values = _labelled_region_values(
            lines,
            table_i_start + 1,
            (_TABLE_II_HEADING_RE, _REMARKS_HEADING_RE),
            _TABLE_I_LABELS,
        )
    table_ii_start = next(
        (i for i, raw in enumerate(lines) if _TABLE_II_HEADING_RE.search(raw)),
        None,
    )
    if table_ii_start is not None:
        slots.table_ii_values = _labelled_region_values(
            lines,
            table_ii_start + 1,
            (_REMARKS_HEADING_RE,),
            _TABLE_II_LABELS,
        )


def _table_grid(
    labels: tuple[tuple[str, str, str], ...],
    values: dict[str, str],
    *,
    date_key: str,
    amount_key: str,
) -> ResolvedGrid | None:
    if not values.get("class_title"):
        return None
    date_ok = parse_date(values.get(date_key, ""), reference_year=None) is not None
    amount_ok = NUMERIC_TOKEN_RE.match(values.get(amount_key, "")) is not None
    if not (date_ok or amount_ok):
        return None
    headers = tuple(header for _l, _k, header in labels)
    row = tuple(values.get(key, "") for _l, key, _h in labels)
    return ResolvedGrid(
        rows=(headers, row), column_alignments=(), column_widths=(), confidence=1.0
    )


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
        if TABLE_I_MARKER_RE.search(line):
            break
        if BOX_3A_TITLE_RE.search(line):
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
        if TABLE_I_MARKER_RE.search(line) or "instructions:" in lower:
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

        current_rec = apply_box3_label(line, lines, idx, current_rec, reference_year)

    if current_rec and current_rec.units_sold:
        slots.proposed_sales.append(current_rec)

    # Step 3: Vertical Block scanning
    if not slots.proposed_sales:
        for idx in range(cutoff):
            line = strip_markup_tags(lines[idx])
            if not line or is_form144_instruction_line(line):
                continue
            lower = line.lower()
            if TABLE_I_MARKER_RE.search(line):
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
                        or TABLE_I_MARKER_RE.search(v_l)
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
        ("1(d) ADDRESS OF ISSUER",),
        (slots.issuer_address or "",),
        ("(e) TELEPHONE NO.", slots.issuer_phone or ""),
        (
            "2(a) NAME OF PERSON FOR WHOSE ACCOUNT THE SECURITIES ARE TO BE SOLD",
            slots.reporting_person or "",
        ),
        ("(c) RELATIONSHIP TO ISSUER", slots.relationship or ""),
        ("2(c) ADDRESS STREET CITY STATE ZIP CODE",),
        (slots.filer_address or "",),
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
    _extract_ascii_tables(lines, slots)

    # Require at least issuer_name or reporting_person to consider it a Form 144
    if not slots.issuer_name and not slots.reporting_person:
        return None

    cover_grid, b3_grid, sig_grid = _build_grids(slots)
    table_i_grid = _table_grid(
        _TABLE_I_LABELS,
        slots.table_i_values,
        date_key="acquired_date",
        amount_key="amount_acquired",
    )
    table_ii_grid = _table_grid(
        _TABLE_II_LABELS,
        slots.table_ii_values,
        date_key="sale_date",
        amount_key="amount_sold",
    )

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
    table_i_sec = (
        ClassifiedSection(
            role=SectionRole.TABLE_I,
            table_index=3,
            raw_node=None,
            resolved_grid=table_i_grid,
        )
        if table_i_grid is not None
        else None
    )
    table_ii_sec = (
        ClassifiedSection(
            role=SectionRole.TABLE_II,
            table_index=4,
            raw_node=None,
            resolved_grid=table_ii_grid,
        )
        if table_ii_grid is not None
        else None
    )

    return Form144Sections(
        cover_box_1_2=cover_sec,
        proposed_sale_box_3=b3_sec,
        table_i=table_i_sec,
        table_ii=table_ii_sec,
        signatures=[sig_sec],
        remarks=[],
        unparsed=[],
    )


__all__ = [
    "Form144AsciiSlots",
    "ProposedSaleRecord",
    "parse_ascii_form144",
]
