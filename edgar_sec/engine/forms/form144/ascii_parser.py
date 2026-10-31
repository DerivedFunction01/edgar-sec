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
    extract_ascii_proposed_sales,
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
_WIDE_WHITESPACE_RE = re.compile(r"\s{4,}")

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


def _split_line_columns(line: str) -> list[str]:
    inner = line.strip(" \t|")
    if inner.count("|") >= 1:
        parts = inner.split("|")
    else:
        parts = WHITESPACE_COLUMN_SPLIT_RE.split(inner)
    return [c.strip(" \t|") for c in parts if c.strip(" \t|")]


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
                            and not is_cover_header_or_subbox_line(cand_l)
                        ):
                            if ":" in cand_l and any(
                                k in cand_l.partition(":")[0].lower()
                                for k in ("issuer", "name", "1(a)", "1 (a)")
                            ):
                                cand = clean_field_candidate(
                                    cand_l.partition(":")[2].strip()
                                )
                                if (
                                    cand
                                    and len(cand) > 2
                                    and not is_cover_header_or_subbox_line(cand)
                                ):
                                    slots.issuer_name = cand
                                    break
                            cols = _split_line_columns(cand_l)
                            if not cols:
                                continue
                            first_col = clean_field_candidate(cols[0])
                            if (
                                first_col
                                and len(first_col) > 2
                                and not is_cover_header_or_subbox_line(first_col)
                                and not IRS_RE.search(first_col)
                                and not SEC_FILE_BARE_RE.search(first_col)
                            ):
                                first_col = first_col.partition("(")[0].strip(
                                    " \t|,:;-"
                                )
                                slots.issuer_name = first_col
                                if len(cols) > 1 and IRS_RE.search(cols[1]):
                                    slots.issuer_irs = IRS_RE.search(cols[1]).group(0)
                                if len(cols) > 2 and SEC_FILE_BARE_RE.search(cols[2]):
                                    slots.issuer_sec_no = SEC_FILE_BARE_RE.search(
                                        cols[2]
                                    ).group(0)
                                break
                            elif first_col and (
                                IRS_RE.search(first_col)
                                or SEC_FILE_BARE_RE.search(first_col)
                            ):
                                break
            if not slots.issuer_name and idx > 0:
                p_l = strip_markup_tags(lines[idx - 1]).strip()
                if (
                    p_l
                    and len(p_l) > 2
                    and not is_horizontal_rule_line(p_l)
                    and not is_cover_header_or_subbox_line(p_l)
                ):
                    slots.issuer_name = clean_field_candidate(p_l)

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
                            and not is_cover_header_or_subbox_line(cand_l)
                        ):
                            if ":" in cand_l and any(
                                k in cand_l.partition(":")[0].lower()
                                for k in (
                                    "person",
                                    "name",
                                    "whose account",
                                    "2(a)",
                                    "2 (a)",
                                )
                            ):
                                cand = clean_field_candidate(
                                    cand_l.partition(":")[2].strip()
                                )
                                if (
                                    cand
                                    and len(cand) > 2
                                    and not is_cover_header_or_subbox_line(cand)
                                    and not cand[0].isdigit()
                                    and not cand.startswith("%")
                                ):
                                    slots.reporting_person = cand
                                    break
                            cols = _split_line_columns(cand_l)
                            if not cols:
                                continue
                            first_col = clean_field_candidate(cols[0])
                            if (
                                first_col
                                and len(first_col) > 2
                                and not is_cover_header_or_subbox_line(first_col)
                                and not first_col[0].isdigit()
                                and not first_col.startswith("%")
                                and not first_col.endswith("%")
                                and first_col.lower()
                                not in (
                                    "director",
                                    "officer",
                                    "shareholder",
                                    "10% owner",
                                    "employee",
                                    "other",
                                    "trustee",
                                    "beneficiary",
                                )
                            ):
                                slots.reporting_person = first_col
                                if not slots.relationship and len(cols) > 1:
                                    for c in cols[1:]:
                                        rel_cand = clean_field_candidate(c)
                                        if (
                                            rel_cand
                                            and len(rel_cand) > 1
                                            and not rel_cand[0].isdigit()
                                            and not is_cover_header_or_subbox_line(
                                                rel_cand
                                            )
                                        ):
                                            low = rel_cand.lower()
                                            if any(
                                                term in low
                                                for term in (
                                                    "officer",
                                                    "director",
                                                    "stockholder",
                                                    "10%",
                                                    "affiliate",
                                                    "trustee",
                                                )
                                            ):
                                                slots.relationship = rel_cand
                                                break
                                if idx + d + 1 < len(lines):
                                    nxt_l = strip_markup_tags(
                                        lines[idx + d + 1]
                                    ).strip()
                                    nxt_cols = _split_line_columns(nxt_l)
                                    suffixes = (
                                        "company",
                                        "corp",
                                        "inc",
                                        "fund",
                                        "trust",
                                    )
                                    if (
                                        nxt_cols
                                        and len(nxt_cols[0]) < 30
                                        and any(
                                            w in nxt_cols[0].lower() for w in suffixes
                                        )
                                    ):
                                        slots.reporting_person = (
                                            f"{slots.reporting_person} {nxt_cols[0]}"
                                        )
                                break
                            elif first_col and first_col.lower() in (
                                "director",
                                "officer",
                                "shareholder",
                                "10% owner",
                                "employee",
                                "other",
                                "trustee",
                                "beneficiary",
                            ):
                                break
            if not slots.reporting_person and idx > 0:
                p_l = strip_markup_tags(lines[idx - 1]).strip()
                if (
                    p_l
                    and len(p_l) > 2
                    and not is_horizontal_rule_line(p_l)
                    and not is_cover_header_or_subbox_line(p_l)
                    and not p_l[0].isdigit()
                    and not p_l.startswith("%")
                ):
                    slots.reporting_person = clean_field_candidate(p_l)

        # 2(b) or 2(c) RELATIONSHIP
        if not slots.relationship and RELATIONSHIP_LABEL_RE.search(line):
            m_rel = RELATIONSHIP_TAIL_RE.search(line)
            cand = clean_field_candidate(m_rel.group(1)) if m_rel else None
            if not cand and idx > 0:
                p_l = strip_markup_tags(lines[idx - 1]).strip()
                cand_p = clean_field_candidate(p_l)
                if cand_p and len(cand_p) > 1 and not cand_p[0].isdigit():
                    cand = cand_p
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
    if tail and len(tail) > 3 and not is_cover_header_or_subbox_line(tail):
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
            or is_cover_header_or_subbox_line(cand)
        ):
            if parts:
                break
            continue
        inner = cand.strip(" \t|")
        if inner.count("|") >= 1:
            val = inner.split("|")[0].strip()
        elif _WIDE_WHITESPACE_RE.search(inner):
            cols = [c.strip() for c in _WIDE_WHITESPACE_RE.split(inner) if c.strip()]
            val = cols[0] if cols else inner
        else:
            val = inner
        parts.append(val)
        if len(parts) >= 2:
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
    t1 = next(
        (i for i, raw in enumerate(lines) if _TABLE_I_HEADING_RE.search(raw)), None
    )
    if t1 is not None:
        slots.table_i_values = _labelled_region_values(
            lines, t1 + 1, (_TABLE_II_HEADING_RE, _REMARKS_HEADING_RE), _TABLE_I_LABELS
        )
    t2 = next(
        (i for i, raw in enumerate(lines) if _TABLE_II_HEADING_RE.search(raw)), None
    )
    if t2 is not None:
        slots.table_ii_values = _labelled_region_values(
            lines, t2 + 1, (_REMARKS_HEADING_RE,), _TABLE_II_LABELS
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
    b3_rows = [header] + [
        (
            s.class_of_sec or "",
            s.broker_name or "",
            s.units_sold or "",
            s.market_value or "",
            s.shares_outstanding or "",
            s.approx_sale_date or "",
            s.exchange or "",
        )
        for s in slots.proposed_sales
    ]
    b3_grid = ResolvedGrid(
        rows=tuple(b3_rows), column_alignments=(), column_widths=(), confidence=1.0
    )
    sig_rows = (
        (slots.sig_date or "", f"/s/ {slots.sig_name}" if slots.sig_name else ""),
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
    slots.proposed_sales = extract_ascii_proposed_sales(lines, reference_year)
    _extract_ascii_tables(lines, slots)

    # Require at least issuer_name or reporting_person to consider it a Form 144
    if not slots.issuer_name and not slots.reporting_person:
        return None

    cover_grid, b3_grid, sig_grid = _build_grids(slots)
    t1_grid = _table_grid(
        _TABLE_I_LABELS,
        slots.table_i_values,
        date_key="acquired_date",
        amount_key="amount_acquired",
    )
    t2_grid = _table_grid(
        _TABLE_II_LABELS,
        slots.table_ii_values,
        date_key="sale_date",
        amount_key="amount_sold",
    )

    return Form144Sections(
        cover_box_1_2=ClassifiedSection(SectionRole.COVER_BOX_1_2, 0, None, cover_grid),
        proposed_sale_box_3=ClassifiedSection(
            SectionRole.PROPOSED_SALE_BOX_3, 1, None, b3_grid
        ),
        table_i=ClassifiedSection(SectionRole.TABLE_I, 3, None, t1_grid)
        if t1_grid
        else None,
        table_ii=ClassifiedSection(SectionRole.TABLE_II, 4, None, t2_grid)
        if t2_grid
        else None,
        signatures=[ClassifiedSection(SectionRole.SIGNATURES, 2, None, sig_grid)],
        remarks=[],
        unparsed=[],
    )


__all__ = [
    "Form144AsciiSlots",
    "ProposedSaleRecord",
    "parse_ascii_form144",
]
