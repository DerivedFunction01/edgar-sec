"""ASCII Form 4 header and signature extraction."""

from __future__ import annotations

import re

from edgar_sec.domain.forms.common.checkmarks import (
    CANONICAL_CHECKED,
    CANONICAL_UNCHECKED,
)
from edgar_sec.engine.forms.common.signatures import (
    extract_clean_signatory_name,
    extract_columnar_signature_and_date,
    extract_signature_candidate,
)
from edgar_sec.engine.forms.ownership.sections import (
    ClassifiedSection,
    SectionRole,
)
from edgar_sec.engine.tables.ascii_html.model import (
    HorizontalAlign,
    ResolvedGrid,
)
from edgar_sec.foundation.regex.builder import build_alternation

_ITEM1_RE = re.compile(
    r"\b1\.\s+name and address|\bname and address of reporting person",
    re.IGNORECASE,
)
_ITEM2_RE = re.compile(r"\b2\.\s+issuer name|\bissuer name and ticker", re.IGNORECASE)
_ITEM6_RE = re.compile(
    r"\b6\.\s+relationship|\brelationship of reporting person", re.IGNORECASE
)
_ITEM7_RE = re.compile(r"\b7\.\s+individual|\bindividual or joint", re.IGNORECASE)
_TABLE_START_TERMS = (
    r"TABLE\s+I\b",
    r"NON-DERIVATIVE SECURITIES",
    r"NON-DERIVATIVE SECURITES",
)
_TABLE_START_ALT = build_alternation(_TABLE_START_TERMS, auto_escape=False)
_TABLE_START_RE = re.compile(_TABLE_START_ALT, re.IGNORECASE)
_HORIZONTAL_RULE_RE = re.compile(r"^[\s\-=+_|]{4,}$")

_IRS_TERMS = (
    r"\bi\.?r\.?s\.?\b",
    r"social security",
    r"identification number",
)
_IRS_ALT = build_alternation(_IRS_TERMS, auto_escape=False)

_ITEM_HEADER_SPECS = (
    ("owner", re.compile(r"(?:1\.\s+)?name and address of report", re.IGNORECASE)),
    ("issuer", re.compile(r"(?:2\.\s+)?issuer name and ticker", re.IGNORECASE)),
    ("irs", re.compile(rf"(?:3\.\s+)?(?:{_IRS_ALT})", re.IGNORECASE)),
    ("period", re.compile(r"(?:4\.\s+)?statement for month", re.IGNORECASE)),
    ("amend", re.compile(r"(?:5\.\s+)?if a[dm]endment", re.IGNORECASE)),
    (
        "relation",
        re.compile(r"(?:6\.\s+)?relationship of reporting person", re.IGNORECASE),
    ),
    ("filing", re.compile(r"(?:7\.\s+)?individual or joint", re.IGNORECASE)),
)
_DATE_LABEL_RE = re.compile(
    r"\bDATE\b\s*\n\s*([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})", re.IGNORECASE
)
_RE_FILL_CHECKED = re.compile(r"_{1,8}\s*[Xx]\s*_{1,8}")
_RE_FILL_BLANK = re.compile(r"_{2,}")

_WRAP_IGNORE_TERMS = (
    r"ing\s+person\*?",
    r"applicable\)?",
)
_WRAP_IGNORE_ALT = build_alternation(_WRAP_IGNORE_TERMS, auto_escape=False)
_RE_WRAP_IGNORE = re.compile(rf"^(?:{_WRAP_IGNORE_ALT})$", re.IGNORECASE)


def _unfold_side_by_side_columns(lines: list[str]) -> list[str]:
    pipe_rows = [
        l
        for l in lines
        if l.strip().startswith("|") and l.strip().endswith("|") and l.count("|") >= 2
    ]
    if len(pipe_rows) >= 5:
        cols: dict[int, list[str]] = {}
        for l in pipe_rows:
            cells = [c.strip() for c in l.split("|")[1:-1]]
            for i, c in enumerate(cells):
                if c and not _HORIZONTAL_RULE_RE.match(c):
                    cols.setdefault(i, []).append(c)
        unfolded: list[str] = []
        for i in sorted(cols.keys()):
            for c in cols[i]:
                if not _RE_WRAP_IGNORE.match(c):
                    unfolded.append(c)
        return unfolded

    col2_idx: int | None = None
    col7_idx: int | None = None
    for line in lines:
        if col2_idx is None:
            m2 = _ITEM2_RE.search(line)
            if m2 and m2.start() > 10:
                col2_idx = m2.start()
        if col7_idx is None:
            m7 = _ITEM7_RE.search(line)
            if m7 and m7.start() > 10:
                col7_idx = m7.start()

    if col2_idx is None and col7_idx is None:
        return lines

    col1: list[str] = []
    col2: list[str] = []
    in_1_to_5 = False
    in_6_7 = False

    for line in lines:
        if _ITEM1_RE.search(line):
            in_1_to_5 = True
        if _ITEM6_RE.search(line):
            in_1_to_5 = False
            in_6_7 = True

        if in_1_to_5 and col2_idx:
            left = line[:col2_idx].rstrip()
            right = line[col2_idx:].strip() if len(line) > col2_idx else ""
            if left:
                col1.append(left)
            if right:
                col2.append(right)
        elif in_6_7 and col7_idx:
            left = line[:col7_idx].rstrip()
            right = line[col7_idx:].strip() if len(line) > col7_idx else ""
            if left:
                col1.append(left)
            if right:
                col2.append(right)
        else:
            col1.append(line)

    return col1 + col2


def extract_ascii_header_and_signatures(
    text: str,
    reference_year: int | None = None,
) -> tuple[ClassifiedSection | None, ClassifiedSection | None]:
    """Extract synthetic ClassifiedSections for Boxes 1-7 and signatures."""
    m_tbl = _TABLE_START_RE.search(text)
    hdr_text = text[: m_tbl.start()] if m_tbl else text[: min(len(text), 4000)]
    raw_lines = hdr_text.splitlines()

    lines = _unfold_side_by_side_columns(raw_lines)
    boxes: dict[str, list[str]] = {
        "owner": [],
        "issuer": [],
        "irs": [],
        "period": [],
        "amend": [],
        "relation": [],
        "filing": [],
    }
    current_box: str | None = None

    for raw_l in lines:
        line = raw_l.strip()
        if not line or _HORIZONTAL_RULE_RE.match(line):
            continue
        matched_box = None
        for key, rx in _ITEM_HEADER_SPECS:
            if rx.search(line):
                matched_box = key
                break
        if matched_box is not None:
            current_box = matched_box
            boxes[current_box].append(line)
        elif current_box is not None:
            boxes[current_box].append(line)

    owner_content = "\n".join(boxes["owner"])
    issuer_content = "\n".join(boxes["issuer"])
    period_content = "\n".join(boxes["period"] + boxes["amend"])
    relation_raw = "\n".join(boxes["relation"])
    relation_step1 = _RE_FILL_CHECKED.sub(f"{CANONICAL_CHECKED} ", relation_raw)
    relation_content = _RE_FILL_BLANK.sub(f"{CANONICAL_UNCHECKED} ", relation_step1)

    rows = (
        (f"1. {owner_content}", f"2. {issuer_content}"),
        (f"4. {period_content}", ""),
        (f"6. {relation_content}", ""),
    )
    grid = ResolvedGrid(
        rows=rows,
        column_alignments=(HorizontalAlign.LEFT, HorizontalAlign.LEFT),
        column_widths=(50, 50),
    )
    boxes_sec = ClassifiedSection(
        role=SectionRole.BOXES_1_TO_7,
        table_index=0,
        raw_node=None,
        resolved_grid=grid,
    )

    all_lines = text.splitlines()
    start_sig = max(0, int(len(all_lines) * 0.4))
    sig_name, sig_date = extract_columnar_signature_and_date(
        all_lines, start_idx=start_sig, reference_year=reference_year
    )
    if not sig_name or not sig_date:
        tail_text = "\n".join(all_lines[start_sig:])
        cand_name, cand_date = extract_signature_candidate(tail_text)
        if not sig_name and cand_name:
            sig_name = extract_clean_signatory_name(cand_name) or cand_name
        if not sig_date and cand_date:
            sig_date = cand_date
        if not sig_date and (m_date := _DATE_LABEL_RE.search(tail_text)):
            sig_date = m_date.group(1).strip()

    sig_sec: ClassifiedSection | None = None
    if sig_name or sig_date:
        sig_rows = (
            (
                f"SIGNATURE OF REPORTING PERSON\n/s/ {sig_name or ''}",
                f"DATE\n{sig_date or ''}",
            ),
        )
        sig_grid = ResolvedGrid(
            rows=sig_rows,
            column_alignments=(HorizontalAlign.LEFT, HorizontalAlign.LEFT),
            column_widths=(50, 50),
        )
        sig_sec = ClassifiedSection(
            role=SectionRole.SIGNATURES,
            table_index=99,
            raw_node=None,
            resolved_grid=sig_grid,
        )

    return boxes_sec, sig_sec


__all__ = ["extract_ascii_header_and_signatures"]
