"""ASCII and SGML state machine parser for Form 144 filings."""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from edgar_sec.domain.forms.families.form144.evidence import (
    FORM144_INSTRUCTION_VETO_PHRASES,
)
from edgar_sec.engine.forms.common.entities import (
    IRS_RE,
    normalize_exchange_name,
)
from edgar_sec.engine.forms.common.numbers import format_scaled_number_string
from edgar_sec.engine.forms.common.signatures import (
    extract_clean_signatory_name,
)
from edgar_sec.engine.forms.common.tables import clean_field_candidate
from edgar_sec.engine.forms.form144.patterns import (
    NOTICE_DATE_LABEL_RE,
    SEC_FILE_BARE_RE,
    SEC_FILE_LABEL_RE,
)
from edgar_sec.engine.tables.ascii_html.model import ResolvedGrid
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import parse_date

_INSTRUCTION_ALT = build_alternation(
    FORM144_INSTRUCTION_VETO_PHRASES, auto_escape=True, compact=True
)
_INSTRUCTION_VETO_RE = re.compile(_INSTRUCTION_ALT, re.IGNORECASE)

_NUMBERED_INSTRUCTION_RE = re.compile(
    r"^\s*[123]\s*\.\s*\(\s*[a-g]\s*\)", re.IGNORECASE
)

_SECURITY_CLASS_TERMS = (
    "common",
    "class a",
    "class b",
    "class c",
    "preferred",
    "ordinary",
    "notes",
    "conv",
    "debentures",
    "warrants",
    "options",
    "debt",
)
_SECURITY_CLASS_ALT = build_alternation(_SECURITY_CLASS_TERMS)
_SECURITY_CLASS_RE = re.compile(rf"\b({_SECURITY_CLASS_ALT})\b", re.IGNORECASE)

_SGML_TAG_RE = re.compile(r"</?[A-Za-z]+(?:\s+[^>]*)?>")
_LINE_NUMBER_PREFIX_RE = re.compile(r"^\d+\s*:\s*")
_DELIMITER_LINE_RE = re.compile(r"^[-=_]{4,}$")
_WHITESPACE_SPLIT_RE = re.compile(r"\t+|\s{2,}")
_PERSON_LABEL_TERMS = frozenset(
    {"person", "whose", "account", "securities", "sold", "please", "type", "print"}
)


def _is_person_label_candidate(text: str) -> bool:
    return any(w in text.lower().split() for w in _PERSON_LABEL_TERMS)


_BOX_2_SUB_HEADER_WORDS = frozenset(
    {
        "irs",
        "ident",
        "no",
        "relationship",
        "issuer",
        "address",
        "street",
        "city",
        "state",
        "zip",
        "code",
        "telephone",
        "area",
        "number",
    }
)
_BOX_2_SUB_BOX_LABEL_RE = re.compile(r"^\(?[b-g]\)", re.IGNORECASE)
_WORD_TOKENS_RE = re.compile(r"[a-z]+")


def _is_box2_header_line(text: str) -> bool:
    low = text.lower()
    words = set(_WORD_TOKENS_RE.findall(low))
    if words and words.issubset(_BOX_2_SUB_HEADER_WORDS | _PERSON_LABEL_TERMS):
        return True
    return bool(_BOX_2_SUB_BOX_LABEL_RE.match(low))


_SIGNATURE_LINE_RE = re.compile(
    r"(?:/s/|signature:)\s*(?:/s/\s*)?([A-Za-z\.\,\s\-]+)", re.IGNORECASE
)
_SLASH_S_RE = re.compile(r"/s/\s*([A-Za-z\.\,\s\-]+)")
_STRIP_SLASH_S_RE = re.compile(r"^.*?/s/\s*")

_BOX_1A_RE = re.compile(r"1\s*\(\s*a\s*\)", re.IGNORECASE)
_BOX_1A_TAIL_RE = re.compile(r"1\s*\(\s*a\s*\)[^:]*:\s*(.+)$", re.IGNORECASE)
_BOX_1B_IRS_RE = re.compile(r"(?:1\s*\(\s*b\s*\)|\(\s*b\s*\))\s*IRS", re.IGNORECASE)
_BOX_1C_SEC_RE = re.compile(
    r"(?:1\s*\(\s*c\s*\)|\(\s*c\s*\))\s*S?\.?E?\.?C?", re.IGNORECASE
)
_BOX_2A_RE = re.compile(r"2\s*\(\s*a\s*\)", re.IGNORECASE)
_BOX_2A_TAIL_RE = re.compile(r"2\s*\(\s*a\s*\)[^:]*:\s*(.+)$", re.IGNORECASE)
_RELATIONSHIP_RE = re.compile(r"RELATIONSHIP\s+TO\s+ISSUER", re.IGNORECASE)
_RELATIONSHIP_TAIL_RE = re.compile(
    r"RELATIONSHIP\s+TO\s+ISSUER\s*:?\s*(.+)$", re.IGNORECASE
)

_BOX_3A_RE = re.compile(r"3\s*\(\s*a\s*\)", re.IGNORECASE)
_BOX_3A_TAIL_RE = re.compile(r"3\s*\(\s*a\s*\)[^:]*:\s*(.+)$", re.IGNORECASE)

_UNITS_TERMS = (
    "number of shares",
    "number of share",
    "number of units",
    "number of unit",
    "units to be sold",
    "unit to be sold",
)
_UNITS_ALT = build_alternation(_UNITS_TERMS)
_BOX_3C_RE = re.compile(
    rf"(?:3\s*\(\s*c\s*\)|\(\s*c\s*\))\s*(?:{_UNITS_ALT})", re.IGNORECASE
)
_BOX_3C_TAIL_RE = re.compile(
    r"(?:to be sold|\(c\)[^:]*):?\s*([0-9][0-9,]*(?:\.[0-9]+)?\s*[A-Za-z]*)",
    re.IGNORECASE,
)
_BOX_3C_NEXT_LINE_RE = re.compile(
    r"(?:instr\.\s*3\(c\):\s*)?([0-9][0-9,]*(?:\.[0-9]+)?\s*[A-Za-z]*)",
    re.IGNORECASE,
)

_BOX_3D_RE = re.compile(
    r"(?:3\s*\(\s*d\s*\)|\(\s*d\s*\))\s*Aggregate\s+Market", re.IGNORECASE
)
_BOX_3D_TAIL_RE = re.compile(
    r"market\s+value[^:]*:?\s*([\$€£]?\s*[0-9][0-9,]*(?:\.[0-9]+)?\s*[A-Za-z]*)",
    re.IGNORECASE,
)
_BOX_3G_RE = re.compile(
    r"(?:3\s*\(\s*g\s*\)|\(\s*g\s*\))\s*Name\s+of\s+Each\s+Securities\s+Exchange",
    re.IGNORECASE,
)
_FOOTNOTE_SUFFIX_RE = re.compile(r"\s*[\(\[]\s*\d+\s*[\)\]]\s*$")


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


def _is_instruction_line(line: str) -> bool:
    if _NUMBERED_INSTRUCTION_RE.search(line):
        return True
    return bool(_INSTRUCTION_VETO_RE.search(line))


def _clean_line_text(raw_line: str) -> str:
    cleaned = _LINE_NUMBER_PREFIX_RE.sub("", raw_line).strip()
    return _SGML_TAG_RE.sub(" ", cleaned).strip()


def _extract_signatures(
    lines: list[str], slots: Form144AsciiSlots, total_lines: int
) -> None:
    start_idx = max(0, int(total_lines * 0.45))
    for idx in range(total_lines - 1, start_idx - 1, -1):
        l = _clean_line_text(lines[idx])
        if not l or _DELIMITER_LINE_RE.match(l):
            continue
        lower = l.lower()
        if (
            "intentional misstatements" in lower
            or "criminal violations" in lower
            or "sec 1147" in lower
        ):
            continue

        if not slots.sig_name and ("/s/" in l or "signature:" in lower):
            m = _SIGNATURE_LINE_RE.search(l)
            if m:
                cand = extract_clean_signatory_name(m.group(1))
                if cand:
                    slots.sig_name = cand

        if not slots.sig_name and ("(signature)" in lower or lower == "signature"):
            for d in range(1, 5):
                if idx - d >= 0:
                    above_l = _clean_line_text(lines[idx - d])
                    if (
                        above_l
                        and not _DELIMITER_LINE_RE.match(above_l)
                        and not above_l.lower().startswith("date")
                    ):
                        if "/s/" in above_l:
                            cand = extract_clean_signatory_name(
                                _STRIP_SLASH_S_RE.sub("", above_l)
                            )
                        else:
                            cand = extract_clean_signatory_name(above_l)
                        if cand and not any(
                            k in cand.lower()
                            for k in ("attention:", "signature", "notice", "date")
                        ):
                            slots.sig_name = cand
                            break

        if not slots.sig_date and (
            "date of notice" in lower or lower.startswith("date:")
        ):
            m_date = NOTICE_DATE_LABEL_RE.search(l)
            if m_date:
                slots.sig_date = (m_date.group(1) or m_date.group(2)).strip()
            else:
                for d in (-2, -1, 1, 2):
                    if 0 <= idx + d < total_lines:
                        adj_l = _clean_line_text(lines[idx + d])
                        p_d = parse_date(adj_l)
                        if p_d and "as of" not in adj_l.lower():
                            slots.sig_date = p_d.display
                            break


def _extract_cover_fields(lines: list[str], slots: Form144AsciiSlots) -> None:
    cutoff = min(len(lines), max(30, int(len(lines) * 0.7)))
    for idx in range(cutoff):
        l = _clean_line_text(lines[idx])
        if not l or _is_instruction_line(l):
            continue
        lower = l.lower()

        # 1(a) NAME OF ISSUER
        if not slots.issuer_name and _BOX_1A_RE.search(l) and "issuer" in lower:
            m_tail = _BOX_1A_TAIL_RE.search(l)
            cand = (
                clean_field_candidate(m_tail.group(1))
                if m_tail
                else clean_field_candidate(l[lower.find("name of issuer") + 14 :])
            )
            if cand and len(cand) > 2 and "please type" not in cand.lower():
                slots.issuer_name = cand
            else:
                for d in (1, 2, 3):
                    if idx + d < len(lines):
                        cand_l = _clean_line_text(lines[idx + d])
                        if (
                            cand_l
                            and not _DELIMITER_LINE_RE.match(cand_l)
                            and not _is_instruction_line(cand_l)
                        ):
                            cols = [
                                c.strip()
                                for c in _WHITESPACE_SPLIT_RE.split(cand_l)
                                if c.strip()
                            ]
                            first_col = clean_field_candidate(cols[0])
                            if (
                                first_col
                                and len(first_col) > 2
                                and "please type" not in first_col.lower()
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
        if not slots.issuer_irs and _BOX_1B_IRS_RE.search(l):
            m_irs = IRS_RE.search(l)
            if m_irs:
                slots.issuer_irs = m_irs.group(0)
            elif idx + 1 < len(lines):
                m_irs = IRS_RE.search(lines[idx + 1])
                if m_irs:
                    slots.issuer_irs = m_irs.group(0)

        # 1(c) SEC FILE NO
        if not slots.issuer_sec_no and _BOX_1C_SEC_RE.search(l):
            m_sec = SEC_FILE_LABEL_RE.search(l) or SEC_FILE_BARE_RE.search(l)
            if m_sec:
                slots.issuer_sec_no = m_sec.group(1)

        # 2(a) NAME OF PERSON
        if (
            not slots.reporting_person
            and _BOX_2A_RE.search(l)
            and ("person" in lower or "account" in lower)
        ):
            m_tail = _BOX_2A_TAIL_RE.search(l)
            cand = clean_field_candidate(m_tail.group(1)) if m_tail else None
            if (
                cand
                and len(cand) > 2
                and not _is_person_label_candidate(cand)
                and not cand[0].isdigit()
                and not cand.startswith("%")
            ):
                slots.reporting_person = cand
            else:
                for d in range(1, 15):
                    if idx + d < len(lines):
                        cand_l = _clean_line_text(lines[idx + d])
                        if (
                            cand_l
                            and not _DELIMITER_LINE_RE.match(cand_l)
                            and not _is_instruction_line(cand_l)
                        ):
                            if _is_box2_header_line(cand_l):
                                continue
                            if ":" in cand_l:
                                _, _, val_part = cand_l.partition(":")
                                cand = clean_field_candidate(val_part.strip())
                                if (
                                    cand
                                    and len(cand) > 2
                                    and not _is_person_label_candidate(cand)
                                    and not cand[0].isdigit()
                                    and not cand.startswith("%")
                                ):
                                    slots.reporting_person = cand
                                    break
                            cols = [
                                c.strip()
                                for c in _WHITESPACE_SPLIT_RE.split(cand_l)
                                if c.strip()
                            ]
                            first_col = clean_field_candidate(cols[0])
                            if (
                                first_col
                                and len(first_col) > 2
                                and not _is_person_label_candidate(first_col)
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
        if not slots.relationship and _RELATIONSHIP_RE.search(l):
            m_rel = _RELATIONSHIP_TAIL_RE.search(l)
            cand = clean_field_candidate(m_rel.group(1)) if m_rel else None
            if cand and len(cand) > 1:
                slots.relationship = cand
            elif idx + 1 < len(lines):
                next_l = _clean_line_text(lines[idx + 1])
                cand = clean_field_candidate(next_l)
                if cand and len(cand) > 1 and not cand.startswith("2("):
                    slots.relationship = cand


def _extract_proposed_sales(
    lines: list[str], slots: Form144AsciiSlots, full_text: str
) -> None:
    cutoff = min(len(lines), max(40, int(len(lines) * 0.85)))

    # Step 1: Scan for Columnar Data Rows (e.g. SGML or monospace tables)
    columnar_recs: list[ProposedSaleRecord] = []
    in_b3 = False
    divider_seen = False
    for idx in range(cutoff):
        l = _clean_line_text(lines[idx])
        if not l or _is_instruction_line(l):
            continue
        lower = l.lower()
        if "table i" in lower or "table 1" in lower:
            break
        if "3(a)" in lower or "3 (a)" in lower:
            in_b3 = True
        if in_b3 and _DELIMITER_LINE_RE.match(l):
            divider_seen = True
            continue

        cols = [c.strip() for c in _WHITESPACE_SPLIT_RE.split(l) if c.strip()]
        is_sec = bool(cols and _SECURITY_CLASS_RE.search(cols[0]))
        if cols and (is_sec or (divider_seen and len(cols) >= 3)):
            rec = ProposedSaleRecord(class_of_sec=cols[0])
            for c in cols[1:]:
                clean_c = _FOOTNOTE_SUFFIX_RE.sub("", c).strip()
                if not rec.units_sold:
                    val = format_scaled_number_string(clean_c)
                    if val and "$" not in clean_c:
                        rec.units_sold = val
                        continue
                if rec.units_sold and not rec.market_value:
                    val = format_scaled_number_string(clean_c)
                    if val:
                        rec.market_value = val
                        continue
                if not rec.exchange and normalize_exchange_name(clean_c):
                    rec.exchange = normalize_exchange_name(clean_c)
                    continue
                if not rec.approx_sale_date and parse_date(clean_c):
                    parsed_d = parse_date(clean_c)
                    if parsed_d:
                        rec.approx_sale_date = parsed_d.display
                    continue
                if (
                    not rec.broker_name
                    and len(clean_c) > 3
                    and not clean_c[0].isdigit()
                ):
                    rec.broker_name = clean_c
            if rec.units_sold:
                columnar_recs.append(rec)

    if columnar_recs:
        slots.proposed_sales.extend(columnar_recs)
        return

    # Step 2: Key-Value forward scanning
    current_rec: ProposedSaleRecord | None = None
    for idx in range(cutoff):
        l = _clean_line_text(lines[idx])
        if not l or _is_instruction_line(l):
            continue
        lower = l.lower()
        if "table i" in lower or "table 1" in lower:
            break
        if "see instr" in lower or "broker-dealer" in lower:
            continue

        # Check for 3(a) Anchor
        m_3a = _BOX_3A_RE.search(l)
        if m_3a:
            if current_rec and current_rec.units_sold:
                slots.proposed_sales.append(current_rec)
            current_rec = ProposedSaleRecord()
            m_tail = _BOX_3A_TAIL_RE.search(l)
            if m_tail:
                cand = clean_field_candidate(m_tail.group(1))
                if cand and "class of" not in cand.lower():
                    current_rec.class_of_sec = cand
            else:
                tail = _BOX_3A_RE.sub("", l).strip()
                cand = clean_field_candidate(tail)
                if (
                    cand
                    and len(cand) > 2
                    and "title" not in cand.lower()
                    and "class" not in cand.lower()
                ):
                    current_rec.class_of_sec = cand
                elif idx + 1 < len(lines):
                    cand = clean_field_candidate(_clean_line_text(lines[idx + 1]))
                    if cand and not cand.startswith("3("):
                        current_rec.class_of_sec = cand

        # Check for 3(c) Units to be sold
        if _BOX_3C_RE.search(l):
            if current_rec is None:
                current_rec = ProposedSaleRecord()
            m_tail = _BOX_3C_TAIL_RE.search(l)
            val = format_scaled_number_string(m_tail.group(1)) if m_tail else None
            if val:
                current_rec.units_sold = val
            else:
                for d in (1, 2, 3):
                    if idx + d < len(lines):
                        cand_l = _clean_line_text(lines[idx + d])
                        if "see instr" in cand_l.lower():
                            continue
                        m_n = _BOX_3C_NEXT_LINE_RE.search(cand_l)
                        val2 = (
                            format_scaled_number_string(m_n.group(1)) if m_n else None
                        )
                        if val2:
                            current_rec.units_sold = val2
                            break

        # Check for 3(d) Market Value
        if _BOX_3D_RE.search(l):
            if current_rec is None:
                current_rec = ProposedSaleRecord()
            m_mv = _BOX_3D_TAIL_RE.search(l)
            val = format_scaled_number_string(m_mv.group(1)) if m_mv else None
            if val:
                current_rec.market_value = val

        # Check for 3(g) Exchange
        if _BOX_3G_RE.search(l):
            if current_rec is None:
                current_rec = ProposedSaleRecord()
            ex = normalize_exchange_name(l)
            if ex:
                current_rec.exchange = ex
            elif idx + 1 < len(lines):
                ex2 = normalize_exchange_name(_clean_line_text(lines[idx + 1]))
                if ex2:
                    current_rec.exchange = ex2

    if current_rec and current_rec.units_sold:
        slots.proposed_sales.append(current_rec)

    # Step 3: Vertical Block scanning
    if not slots.proposed_sales:
        for idx in range(cutoff):
            l = _clean_line_text(lines[idx])
            if not l or _is_instruction_line(l):
                continue
            lower = l.lower()
            if "table i" in lower or "table 1" in lower:
                break
            if _SECURITY_CLASS_RE.search(l) and len(l) < 50:
                rec = ProposedSaleRecord(class_of_sec=l)
                for d in range(1, 30):
                    if idx + d >= len(lines):
                        break
                    v_l = _clean_line_text(lines[idx + d])
                    if not v_l or _is_instruction_line(v_l):
                        continue
                    v_low = v_l.lower()
                    if (
                        "instructions:" in v_low
                        or "table i" in v_low
                        or "table 1" in v_low
                        or "potential persons" in v_low
                    ):
                        break
                    clean_v = _FOOTNOTE_SUFFIX_RE.sub("", v_l).strip()
                    num = format_scaled_number_string(clean_v)
                    if num and not rec.units_sold and "$" not in clean_v:
                        rec.units_sold = num
                    elif num and rec.units_sold and not rec.market_value:
                        rec.market_value = num
                    elif num and rec.market_value and not rec.shares_outstanding:
                        rec.shares_outstanding = num
                    elif not rec.exchange and normalize_exchange_name(clean_v):
                        rec.exchange = normalize_exchange_name(clean_v)
                    elif not rec.approx_sale_date and parse_date(clean_v):
                        parsed_d = parse_date(clean_v)
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
                sale.class_of_sec or "Common Stock",
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


def parse_ascii_form144(raw_text: str) -> Form144Sections | None:
    """Parse Form 144 from ASCII / SGML / PRE text into Form144Sections."""
    from edgar_sec.engine.forms.form144.sections import (
        ClassifiedSection,
        Form144Sections,
        SectionRole,
    )

    lines = raw_text.splitlines()
    if not lines:
        return None

    slots = Form144AsciiSlots()
    total_lines = len(lines)

    _extract_signatures(lines, slots, total_lines)
    _extract_cover_fields(lines, slots)
    _extract_proposed_sales(lines, slots, raw_text)

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
