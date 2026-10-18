"""Table and footnote extraction for historical ASCII Form 4 filings."""

from __future__ import annotations

import re

from edgar_sec.engine.forms.ownership.ascii_shape import AsciiShape
from edgar_sec.engine.forms.ownership.sections import (
    ClassifiedSection,
    SectionRole,
)
from edgar_sec.engine.tables.ascii_html.model import (
    HorizontalAlign,
    ResolvedGrid,
)
from edgar_sec.foundation.regex.builder import build_alternation

_TABLE_TAG_RE = re.compile(r"<TABLE>(.*?)</TABLE>", re.IGNORECASE | re.DOTALL)
_SC_LINE_RE = re.compile(r"<\s*S\s*>", re.IGNORECASE)
_SC_TOKEN_RE = re.compile(r"<\s*[SC]\s*>", re.IGNORECASE)
_UNDERSCORE_RULE_RE = re.compile(r"^_{20,}", re.MULTILINE)
_HORIZONTAL_RULE_RE = re.compile(r"^[\s\-=+|_]{4,}$")
_EXPLANATION_TERMS = (
    r"explanation of responses",
    r"<FN>",
    r"footnotes\s*:",
)
_EXPLANATION_ALT = build_alternation(_EXPLANATION_TERMS, auto_escape=False)
_EXPLANATION_RE = re.compile(_EXPLANATION_ALT, re.IGNORECASE)

_RE_TABLE_I_OR_II = re.compile(r"^\s*Table\s+I{1,2}\b", re.IGNORECASE)
_RE_PIPE_RULE = re.compile(r"^\|?[-=+|]{10,}\|?$")
_RE_SLASH_DIGIT = re.compile(r"/\d+$")
_RE_TABLE_I = re.compile(r"Table\s+I\b", re.IGNORECASE)
_RE_TABLE_II = re.compile(r"Table\s+II\b", re.IGNORECASE)
_RE_LINE_TABLE_II = re.compile(r"(?:\n|^)[^\n]*Table\s+II\b", re.IGNORECASE)
_RE_TABLE_II_PART2 = re.compile(
    r"(?:\n|^)[^\n]*Table\s+II\s*\(PART\s*2\)", re.IGNORECASE
)
_RE_STANZA_SPLIT = re.compile(r"(?:\n|^)\s*1\.\s+Title of Security", re.IGNORECASE)
_RE_STANZA_TITLE = re.compile(r"^:\s*([^\n]+)")
_RE_STANZA_DATE = re.compile(r"Transaction Date[^\n]*:\s*([^\n]+)", re.IGNORECASE)
_RE_STANZA_CODE = re.compile(r"Transaction Code[^\n]*:\s*Code\s*([A-Z])", re.IGNORECASE)
_RE_STANZA_AMT = re.compile(r"Amount\s*:\s*([\d,]+)", re.IGNORECASE)
_RE_STANZA_AD = re.compile(r"\(A\)\s*or\s*\(D\)\s*:\s*([AD])", re.IGNORECASE)
_RE_STANZA_PRICE = re.compile(r"Price\s*:\s*([^\s\n]+)", re.IGNORECASE)
_RE_STANZA_OWNED = re.compile(r"Beneficially Owned[^\n]*:\s*([\d,]+)", re.IGNORECASE)
_RE_STANZA_FORM = re.compile(
    r"Direct\s*\(D\)\s*or\s*Indirect\s*\(I\)\s*:\s*([DI])", re.IGNORECASE
)
_RE_STANZA_NATURE = re.compile(r"Nature of Indirect[^\n]*:\s*([^\n]+)", re.IGNORECASE)
_SIG_FN_TERMS = (r"/s/", r"signature of reporting")
_SIG_FN_ALT = build_alternation(_SIG_FN_TERMS, auto_escape=False)
_RE_SIG_FN = re.compile(_SIG_FN_ALT, re.IGNORECASE)


_T1_HDR_ROW = (
    "Title of Security",
    "Transaction Date",
    "Deemed Execution Date",
    "Transaction Code",
    "Equity Swap",
    "Amount",
    "A/D",
    "Price",
    "Owned Following",
    "Direct/Indirect",
    "Nature of Ownership",
)

_T2_HDR_ROW = (
    "Title of Derivative Security",
    "Conversion Price",
    "Transaction Date",
    "Deemed Execution Date",
    "Transaction Code",
    "Equity Swap",
    "Amount",
    "A/D",
    "Date Exercisable",
    "Expiration Date",
    "Underlying Title",
    "Underlying Amount",
    "Price",
    "Owned Following",
    "Direct/Indirect",
    "Nature of Ownership",
)


def _parse_sc_block(lines: list[str]) -> list[tuple[str, ...]]:
    sc_line: str | None = None
    sc_idx = -1
    for idx, l in enumerate(lines):
        if _SC_LINE_RE.search(l):
            sc_line = l
            sc_idx = idx
            break
    if not sc_line:
        return []

    col_starts = [m.start() for m in _SC_TOKEN_RE.finditer(sc_line)]
    tbl_rows: list[tuple[str, ...]] = []

    for line in lines[sc_idx + 1 :]:
        s = line.strip()
        if (
            not s
            or s.startswith("</TABLE")
            or s.startswith("<PAGE")
            or _HORIZONTAL_RULE_RE.match(s)
        ):
            continue
        if _EXPLANATION_RE.search(line) or _RE_TABLE_I_OR_II.match(line):
            break

        cells: list[str] = []
        for i in range(len(col_starts)):
            st = col_starts[i]
            en = col_starts[i + 1] if i + 1 < len(col_starts) else len(line)
            cells.append(line[st:en].strip() if st < len(line) else "")

        if any(cells):
            if tbl_rows and not any(cells[1:8]) and (cells[0] or cells[-1]):
                prev = list(tbl_rows[-1])
                if cells[0]:
                    prev[0] = f"{prev[0]} {cells[0]}"
                if cells[-1]:
                    prev[-1] = f"{prev[-1]} {cells[-1]}"
                tbl_rows[-1] = tuple(prev)
            else:
                tbl_rows.append(tuple(cells))

    return tbl_rows


def _process_pipe_lines(sub_lines: list[str]) -> list[tuple[str, ...]]:
    chunks: list[list[list[str]]] = []
    curr_chunk: list[list[str]] = []

    for l in sub_lines:
        if _HORIZONTAL_RULE_RE.match(l) or _RE_PIPE_RULE.match(l.strip()):
            if curr_chunk:
                chunks.append(curr_chunk)
                curr_chunk = []
            continue
        if "<CAPTION>" in l or _EXPLANATION_RE.search(l):
            break
        if "|" in l:
            parts = (
                [p.strip() for p in l.split("|")[1:-1]]
                if l.strip().startswith("|")
                else [p.strip() for p in l.split("|")]
            )
            if any(p for p in parts):
                curr_chunk.append(parts)

    if curr_chunk:
        chunks.append(curr_chunk)

    merged_rows: list[tuple[str, ...]] = []
    for chunk in chunks:
        max_c = max(len(row) for row in chunk)
        merged = [""] * max_c
        for row in chunk:
            for idx, c in enumerate(row):
                if not c:
                    continue
                if not merged[idx]:
                    merged[idx] = c
                else:
                    prev = merged[idx]
                    if (
                        prev.endswith("/")
                        or c.startswith("/")
                        or prev.endswith("-")
                        or (_RE_SLASH_DIGIT.search(prev) and c.isdigit())
                    ):
                        merged[idx] = prev + c
                    else:
                        merged[idx] = prev + " " + c
        header_sample = " ".join(merged[:3]).lower()
        if (
            "title of" in header_sample
            or "conver" in header_sample
            or "trans" in header_sample
            or "table i" in header_sample
            or "table ii" in header_sample
        ):
            continue
        if any(merged):
            merged_rows.append(tuple(merged))

    return merged_rows


def _parse_pipe_tables(
    tables: list[str],
) -> tuple[list[tuple[str, ...]], list[tuple[str, ...]]]:
    combined = "\n".join(tables)
    lines = combined.splitlines()
    t1_lines: list[str] = []
    t2_lines: list[str] = []
    curr: list[str] | None = None

    for l in lines:
        if _RE_TABLE_I.search(l):
            curr = t1_lines
        elif _RE_TABLE_II.search(l):
            curr = t2_lines
        if curr is not None:
            curr.append(l)

    t1_rows = _process_pipe_lines(t1_lines)
    t2_rows = _process_pipe_lines(t2_lines)
    return t1_rows, t2_rows


def _parse_sc_tables(
    tables: list[str],
) -> tuple[list[tuple[str, ...]], list[tuple[str, ...]]]:
    t1_rows: list[tuple[str, ...]] = []
    t2_rows: list[tuple[str, ...]] = []

    for tbl in tables:
        m_t2 = _RE_LINE_TABLE_II.search(tbl)
        if m_t2:
            t1_part = tbl[: m_t2.start()]
            t2_part = tbl[m_t2.start() :]
            t1_rows.extend(_parse_sc_block(t1_part.splitlines()))

            # Check if Table II has Part 1 and Part 2
            m_p2 = _RE_TABLE_II_PART2.search(t2_part)
            if m_p2:
                p1_part = t2_part[: m_p2.start()]
                p2_part = t2_part[m_p2.start() :]
                p1_rows = _parse_sc_block(p1_part.splitlines())
                p2_rows = _parse_sc_block(p2_part.splitlines())
                if len(p1_rows) == len(p2_rows):
                    joined = [
                        r1 + r2[1:] for r1, r2 in zip(p1_rows, p2_rows, strict=True)
                    ]
                    t2_rows.extend(joined)
                else:
                    t2_rows.extend(p1_rows)
            else:
                t2_rows.extend(_parse_sc_block(t2_part.splitlines()))
        else:
            if _RE_TABLE_II.search(tbl):
                t2_rows.extend(_parse_sc_block(tbl.splitlines()))
            else:
                t1_rows.extend(_parse_sc_block(tbl.splitlines()))

    return t1_rows, t2_rows


def _parse_stanzas(
    text: str,
) -> tuple[list[tuple[str, ...]], list[tuple[str, ...]]]:
    m1 = _RE_TABLE_I.search(text)
    m2 = _RE_TABLE_II.search(text)
    m_fn = _EXPLANATION_RE.search(text)
    end_pos = m_fn.start() if m_fn else len(text)

    t1_text = ""
    t2_text = ""
    if m1 and m2:
        t1_text = text[m1.end() : m2.start()]
        t2_text = text[m2.end() : end_pos]
    elif m1:
        t1_text = text[m1.end() : end_pos]

    t1_rows: list[tuple[str, ...]] = []
    # Stanzas of numbered items: 1. Title:, 2. Date:, 3. Code:, 4. Amount:, etc.
    stanzas = _RE_STANZA_SPLIT.split(t1_text)
    for st in stanzas:
        if not st.strip():
            continue
        title_m = _RE_STANZA_TITLE.search(st)
        title = title_m.group(1).strip() if title_m else ""
        date_m = _RE_STANZA_DATE.search(st)
        date = date_m.group(1).strip() if date_m else ""
        code_m = _RE_STANZA_CODE.search(st)
        code = code_m.group(1).strip() if code_m else ""
        amt_m = _RE_STANZA_AMT.search(st)
        amt = amt_m.group(1).strip() if amt_m else ""
        ad_m = _RE_STANZA_AD.search(st)
        ad = ad_m.group(1).strip() if ad_m else ""
        price_m = _RE_STANZA_PRICE.search(st)
        price = price_m.group(1).strip() if price_m else ""
        owned_m = _RE_STANZA_OWNED.search(st)
        owned = owned_m.group(1).strip() if owned_m else ""
        form_m = _RE_STANZA_FORM.search(st)
        form = form_m.group(1).strip() if form_m else ""
        nature_m = _RE_STANZA_NATURE.search(st)
        nature = nature_m.group(1).strip() if nature_m else ""
        if title or date or amt or owned:
            t1_rows.append(
                (title, date, "", code, "", amt, ad, price, owned, form, nature)
            )

    return t1_rows, []


def extract_ascii_tables_and_footnotes(
    text: str,
    shape: AsciiShape,
) -> tuple[
    ClassifiedSection | None,
    ClassifiedSection | None,
    list[ClassifiedSection],
]:
    """Extract synthetic ClassifiedSections for Table I, Table II, and Footnotes."""
    tables = _TABLE_TAG_RE.findall(text)

    if shape in (AsciiShape.PIPE_UNDERSCORE, AsciiShape.FULL_PAGE_TABLE):
        t1_rows, t2_rows = _parse_pipe_tables(tables)
    elif shape == AsciiShape.STANZAS or not tables:
        t1_rows, t2_rows = _parse_stanzas(text)
    else:
        t1_rows, t2_rows = _parse_sc_tables(tables)

    def _build_sec(
        rows: list[tuple[str, ...]],
        hdr_row: tuple[str, ...],
        role: SectionRole,
    ) -> ClassifiedSection | None:
        if not rows:
            return None
        max_c = max(len(hdr_row), max(len(r) for r in rows))
        padded_hdr = hdr_row + ("",) * (max_c - len(hdr_row))
        padded_rows = (padded_hdr,) + tuple(r + ("",) * (max_c - len(r)) for r in rows)
        grid = ResolvedGrid(
            rows=padded_rows,
            column_alignments=(HorizontalAlign.LEFT,) * max_c,
            column_widths=(10,) * max_c,
        )
        return ClassifiedSection(
            role=role,
            table_index=1 if role == SectionRole.TABLE_I else 2,
            raw_node=None,
            resolved_grid=grid,
        )

    t1_sec = _build_sec(t1_rows, _T1_HDR_ROW, SectionRole.TABLE_I)
    t2_sec = _build_sec(t2_rows, _T2_HDR_ROW, SectionRole.TABLE_II)

    # Footnotes extraction
    fn_sections: list[ClassifiedSection] = []
    m_fn = _EXPLANATION_RE.search(text)
    if m_fn:
        fn_text = text[m_fn.start() :]
        # Stop at signature or end of file
        m_sig = _RE_SIG_FN.search(fn_text)
        if m_sig:
            fn_text = fn_text[: m_sig.start()]
        fn_rows = tuple((line,) for line in fn_text.splitlines() if line.strip())
        if fn_rows:
            fn_grid = ResolvedGrid(
                rows=fn_rows,
                column_alignments=(HorizontalAlign.LEFT,),
                column_widths=(80,),
            )
            fn_sections.append(
                ClassifiedSection(
                    role=SectionRole.FOOTNOTES,
                    table_index=90,
                    raw_node=None,
                    resolved_grid=fn_grid,
                )
            )

    return t1_sec, t2_sec, fn_sections


__all__ = ["extract_ascii_tables_and_footnotes"]
