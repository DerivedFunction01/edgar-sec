"""Deep document normalizer with generalized HTML table detection and layout alignment.

Extracts tables, detects multi-tier headers (via <th>, CSS borders, bold density, underlines),
handles colspan expansion, converts data tables to ASCII grids using defs.tables.HTMLTableConverter,
unwraps layout tables, and standardizes SEC Part/Item headers.
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Comment

from defs.regex import build_alternation
from defs.tables import HTMLTableConverter

from .forms.base import PreprocessedDocument

# Regexes for page break markers and XML artifacts
_RE_PAGE_TAG = re.compile(r"(?i)<\/?PAGE\b[^>]*>")
_RE_PAGE_NUM_FOOTER = re.compile(
    r"(?im)^\s*(?:page\s+\d+(?:\s+of\s+\d+)?|\d+\s+of\s+\d+|-\s*\d+\s*-)\s*$"
)
_IXBRL_PREFIXES = build_alternation(["ix", "xbrli", "dei", "us-gaap"])
_RE_XML_IXBRL_TAGS = re.compile(rf"</?(?:{_IXBRL_PREFIXES}):[^>]*>", re.IGNORECASE)
_RE_MULTIPLE_BLANKS = re.compile(r"\n{3,}")
_RE_TRAILING_WHITESPACE = re.compile(r"[ \t]+$", re.MULTILINE)
_RE_TOC_LEADER_DOTS = re.compile(r"(?:\s*\.\s*){5,}\s*(?=\d+\b)")

# Heading normalization
_RE_ITEM_HEADER = re.compile(
    r"(?im)^\s*(item\s+(?:1[0-5]?|[1-9])[a-z]?)\s*[\.:\-–—]\s*(.*?)\s*$"
)
_PART_NUMS = build_alternation([r"i{1,4}", "iv", "v"])
_RE_PART_HEADER = re.compile(rf"(?im)^\s*(part\s+(?:{_PART_NUMS}))\s*[\.:\-–—]?\s*$")

_RE_BORDER_TOP = re.compile(r"border-top:\s*\w+", re.IGNORECASE)
_RE_BORDER_BOTTOM = re.compile(r"border-bottom:\s*\w+", re.IGNORECASE)
_BOLD_WEIGHTS = build_alternation(["bold", r"[6-9]00", "bolder"])
_RE_BOLD_FONT = re.compile(rf"font-weight:\s*(?:{_BOLD_WEIGHTS})", re.IGNORECASE)
_RE_UNDERLINE = re.compile(r"text-decoration:\s*underline", re.IGNORECASE)
_HIDDEN_PROPS = build_alternation([r"display:\s*none", r"visibility:\s*hidden"])
_RE_HIDDEN_STYLE = re.compile(rf"(?:{_HIDDEN_PROPS})", re.IGNORECASE)
_RE_NUMERIC_CELL = re.compile(r"^[\$\€\£]?\s*\(?\s*[\d,\.]+\s*\)?\s*%?$")
_RE_PAREN_SPACES = re.compile(r"\(\s+([^\)]+?)\s+\)")
_RE_FOOTNOTE = re.compile(r"^\(?[a-zA-Z0-9\*\†\‡\§\d]{1,3}\)?$")
_FIN_PLACEHOLDERS = {
    "—",
    "-",
    "–",
    "*",
    "$—",
    "—*",
    "-*",
    "—)",
    "-)",
    "—%",
    "-%",
    "–%",
    "na",
    "n/a",
    "none",
    "nil",
}
_RE_BULLET_MARKER = re.compile(
    r"^(?:[o\*\-\+\u2022\u00b7\x95\u2013\u2014&#149;]|\(?\d{1,2}[\.\)]?|\(?[a-zA-Z][\.\)]?)$"
)


class DeepNormalizer:
    """Stage 3 deep normalization engine with generalized HTML table alignment."""

    def normalize(
        self,
        preprocessed: PreprocessedDocument,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Deeply normalize preprocessed text into clean, structured plain text."""
        _ = metadata
        text = preprocessed.cleaned_text

        # 1. If HTML tags exist and table structures are present, convert HTML tables to ASCII grids
        if preprocessed.has_html_tags and "<table" in text.lower():
            text = self._convert_html_tables_to_ascii(text)

        # 2. Strip non-visual XML / iXBRL tags
        text = _RE_XML_IXBRL_TAGS.sub("", text)

        # 3. Strip page markers (<PAGE>, Page X of Y)
        text = _RE_PAGE_TAG.sub("\n", text)
        text = _RE_PAGE_NUM_FOOTER.sub("", text)

        # 4. Standardize standard item and part headers
        text = self._normalize_headers(text)

        # 5. Clean up TOC leader dots
        text = _RE_TOC_LEADER_DOTS.sub("  ", text)

        # 6. Normalize whitespace
        text = _RE_TRAILING_WHITESPACE.sub("", text)
        text = _RE_MULTIPLE_BLANKS.sub("\n\n", text)

        return text.strip()

    def _convert_html_tables_to_ascii(self, html_content: str) -> str:
        """Parse HTML tables with colspan expansion and multi-tier header detection."""
        try:
            soup = BeautifulSoup(html_content, "lxml")
        except Exception:  # noqa: BLE001 - fallback if lxml parser is unavailable
            soup = BeautifulSoup(html_content, "html.parser")

        # Decompose non-content and hidden elements
        for element in soup(
            ["head", "script", "style", "title", "meta", "noscript", "ix:hidden"]
        ):
            element.decompose()

        for element in soup.find_all(style=_RE_HIDDEN_STYLE):
            element.decompose()

        for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
            comment.extract()

        # Process all <table> elements
        tables = list(soup.find_all("table"))
        for table in tables:
            trs = table.find_all("tr")
            if len(trs) <= 1:
                table.unwrap()
                continue

            # 1. Check for 2-column bullet list layout table
            is_bullet = True
            bullet_items = []
            for tr in trs:
                tds = tr.find_all(["td", "th"])
                if len(tds) == 2:
                    c0 = tds[0].get_text(strip=True)
                    c1 = tds[1].get_text(separator=" ", strip=True)
                    if len(c0) <= 6 and (
                        _RE_BULLET_MARKER.match(c0) or c0 in ("•", "·", "*", "-")
                    ):
                        bullet_items.append((c0, c1))
                    else:
                        is_bullet = False
                        break
                else:
                    is_bullet = False
                    break

            if is_bullet and bullet_items:
                new_div = soup.new_tag("div")
                for marker, content in bullet_items:
                    p_tag = soup.new_tag("p")
                    m_clean = (
                        "•"
                        if marker in ("•", "·", "*", "-", "o", "&#149;")
                        else marker
                    )
                    p_tag.string = f"{m_clean} {content}"
                    new_div.append(p_tag)
                table.replace_with(new_div)
                continue

            # 2. Check for Table of Contents layout table
            full_text = table.get_text()
            if (
                "Item" in full_text
                and "Page" in full_text
                and any(
                    p in full_text
                    for p in ("Part I", "PART I", "Part II", "PART II")
                )
            ):
                table.unwrap()
                continue

            # 3. Check numerical content ratio
            all_cells = table.find_all(["td", "th"])
            num_cells = sum(
                1
                for c in all_cells
                if _RE_NUMERIC_CELL.match(c.get_text(strip=True))
                or c.get_text(strip=True) in ("—", "-", "–")
            )
            non_empty = sum(1 for c in all_cells if c.get_text(strip=True))
            ratio = (num_cells / non_empty) if non_empty else 0
            has_years = bool(
                re.search(r"\b(202[0-9]|201[0-9]|200[0-9]|199[0-9])\b", full_text)
            )

            is_financial = len(trs) >= 3 and (
                ratio >= 0.15 or (has_years and ratio >= 0.08 and num_cells >= 4)
            )

            if not is_financial:
                table.unwrap()
                continue

            raw_grid: list[list[str]] = []
            re_paren_spaces = re.compile(r"\(\s+([^\)]+?)\s+\)")
            re_year = re.compile(r"^\b(202[0-9]|201[0-9]|200[0-9]|199[0-9])\b$")

            # 1. Build physical 2D grid with exact colspan positioning
            try:
                occupied = {}
                for r_idx, tr in enumerate(table.find_all("tr")):
                    c_idx = 0
                    for td in tr.find_all(["td", "th"]):
                        while (r_idx, c_idx) in occupied:
                            c_idx += 1
                        try:
                            colspan = int(td.get("colspan", 1))
                        except Exception:
                            colspan = 1
                        try:
                            rowspan = int(td.get("rowspan", 1))
                        except Exception:
                            rowspan = 1
                        t = td.get_text(separator=" ", strip=True)
                        t = re.sub(r"\s+", " ", t).strip()
                        t = re_paren_spaces.sub(r"(\1)", t)
                        t = re.sub(r"^\$\s+(\d)", r"$\1", t)
                        occupied[(r_idx, c_idx)] = t
                        for ro in range(rowspan):
                            for co in range(colspan):
                                if ro == 0 and co == 0:
                                    continue
                                occupied[(r_idx + ro, c_idx + co)] = ""
                        c_idx += colspan

                if not occupied:
                    table.unwrap()
                    continue

                max_r = max(r for r, c in occupied.keys()) + 1
                max_c = max(c for r, c in occupied.keys()) + 1
                for r in range(max_r):
                    row = [occupied.get((r, c), "") for c in range(max_c)]
                    if any(c.strip() for c in row):
                        raw_grid.append(row)
            except (ValueError, TypeError, KeyError, AttributeError):
                table.unwrap()
                continue

            if not raw_grid:
                table.unwrap()
                continue

            num_cols = max(len(r) for r in raw_grid)
            padded = [r + [""] * (num_cols - len(r)) for r in raw_grid]

            # 2. Detect header rows: cutoff before first real data row (ignoring year headers)
            header_count = 1
            for i, r in enumerate(padded):
                non_empty = [c for c in r if c.strip()]
                non_year_numbers = sum(
                    1
                    for c in non_empty
                    if (
                        _RE_NUMERIC_CELL.match(c)
                        or c.strip().lower() in _FIN_PLACEHOLDERS
                    )
                    and not re_year.match(c)
                )
                ratio = (
                    (non_year_numbers / len(non_empty)) if non_empty else 0
                )
                if ratio >= 0.25:
                    header_count = i
                    break

            # Helper to detect intermediate section header rows in multi-period tables
            def _is_section_header(row: list[str]) -> bool:
                non_empty = [c.strip() for c in row if c.strip()]
                if not non_empty:
                    return True
                return all(
                    not bool(
                        _RE_NUMERIC_CELL.match(c)
                        or c.lower() in _FIN_PLACEHOLDERS
                    )
                    for c in non_empty
                )

            # 3. Sub-column pair merging: if col c and c+1 form a split currency/number pair
            for c in range(0, num_cols - 1):
                is_pair = True
                has_symbol_split = False
                data_rows_count = 0
                for r in range(header_count, len(padded)):
                    if _is_section_header(padded[r]):
                        continue
                    v1 = padded[r][c].strip()
                    v2 = padded[r][c + 1].strip()
                    if not v1 and not v2:
                        continue
                    data_rows_count += 1
                    v1_is_num = bool(
                        _RE_NUMERIC_CELL.match(v1)
                        or v1.lower() in _FIN_PLACEHOLDERS
                    )
                    v2_is_num = bool(
                        _RE_NUMERIC_CELL.match(v2)
                        or v2.lower() in _FIN_PLACEHOLDERS
                    )
                    if v1 in ("$", "€", "£", "¥", "(") and v2_is_num:
                        has_symbol_split = True
                    elif v1_is_num and not v2:
                        pass
                    elif not v1 and v2_is_num:
                        pass
                    else:
                        is_pair = False
                        break
                if is_pair and has_symbol_split and data_rows_count > 0:
                    for r in range(len(padded)):
                        v1 = padded[r][c].strip()
                        v2 = padded[r][c + 1].strip()
                        if r >= header_count and not _is_section_header(
                            padded[r]
                        ):
                            if v1 in ("$", "€", "£", "¥", "(") and v2:
                                padded[r][c] = (
                                    (v1 + v2)
                                    if v1 in ("$", "€", "£", "¥")
                                    else (v1 + " " + v2)
                                )
                                padded[r][c + 1] = ""
                            elif not v1 and v2:
                                padded[r][c] = v2
                                padded[r][c + 1] = ""
                        else:
                            if not v1 and v2:
                                padded[r][c] = v2
                                padded[r][c + 1] = ""

            cols_to_drop = set()

            # 4. Footnote reference columns (sparse single-token '(a)', '(b)', '(1)') -> merge to left
            for c in range(1, num_cols):
                data_cells = [
                    padded[r][c].strip()
                    for r in range(header_count, len(padded))
                    if not _is_section_header(padded[r])
                    and padded[r][c].strip()
                ]
                if (
                    data_cells
                    and all(_RE_FOOTNOTE.match(cell) for cell in data_cells)
                    and len(data_cells) <= (len(padded) - header_count) * 0.6
                ):
                    for r in range(len(padded)):
                        sym = padded[r][c].strip()
                        if (
                            sym
                            and r >= header_count
                            and not _is_section_header(padded[r])
                        ):
                            for prev_c in range(c - 1, -1, -1):
                                if (
                                    prev_c not in cols_to_drop
                                    and padded[r][prev_c].strip()
                                ):
                                    padded[r][prev_c] = (
                                        padded[r][prev_c] + " " + sym
                                    )
                                    break
                        elif sym and (
                            r < header_count or _is_section_header(padded[r])
                        ):
                            for prev_c in range(c - 1, -1, -1):
                                if any(
                                    padded[dr][prev_c].strip()
                                    for dr in range(header_count, len(padded))
                                ):
                                    if not padded[r][prev_c].strip():
                                        padded[r][prev_c] = sym
                                    break
                    cols_to_drop.add(c)

            # 5. Merge trailing and leading symbol columns based on data-row contents
            for c in range(1, num_cols):
                if c in cols_to_drop:
                    continue
                data_cells = [
                    padded[r][c].strip()
                    for r in range(header_count, len(padded))
                    if not _is_section_header(padded[r])
                    and padded[r][c].strip()
                ]
                if data_cells and all(
                    cell in ("%", "pt", "bps", "%)", ")") for cell in data_cells
                ):
                    for r in range(len(padded)):
                        sym = padded[r][c].strip()
                        if (
                            sym
                            and r >= header_count
                            and not _is_section_header(padded[r])
                        ):
                            for prev_c in range(c - 1, -1, -1):
                                if (
                                    prev_c not in cols_to_drop
                                    and padded[r][prev_c].strip()
                                ):
                                    padded[r][prev_c] = (
                                        padded[r][prev_c]
                                        + (
                                            ""
                                            if sym.startswith(("%", ")"))
                                            else " "
                                        )
                                        + sym
                                    )
                                    break
                        elif sym and (
                            r < header_count or _is_section_header(padded[r])
                        ):
                            for prev_c in range(c - 1, -1, -1):
                                if any(
                                    padded[dr][prev_c].strip()
                                    for dr in range(header_count, len(padded))
                                ):
                                    if not padded[r][prev_c].strip():
                                        padded[r][prev_c] = sym
                                    break
                    cols_to_drop.add(c)

            for c in range(0, num_cols - 1):
                if c in cols_to_drop:
                    continue
                data_cells = [
                    padded[r][c].strip()
                    for r in range(header_count, len(padded))
                    if not _is_section_header(padded[r])
                    and padded[r][c].strip()
                ]
                if data_cells and all(
                    cell in ("$", "€", "£", "¥", "(", "-") for cell in data_cells
                ):
                    for r in range(len(padded)):
                        sym = padded[r][c].strip()
                        if (
                            sym
                            and r >= header_count
                            and not _is_section_header(padded[r])
                        ):
                            for next_c in range(c + 1, num_cols):
                                if (
                                    next_c not in cols_to_drop
                                    and padded[r][next_c].strip()
                                ):
                                    padded[r][next_c] = (
                                        sym
                                        + (
                                            ""
                                            if len(sym) == 1
                                            and sym in ("$", "€", "£", "¥", "(")
                                            else " "
                                        )
                                        + padded[r][next_c]
                                    )
                                    break
                        elif sym and (
                            r < header_count or _is_section_header(padded[r])
                        ):
                            for next_c in range(c + 1, num_cols):
                                if any(
                                    padded[dr][next_c].strip()
                                    for dr in range(header_count, len(padded))
                                ):
                                    if not padded[r][next_c].strip():
                                        padded[r][next_c] = sym
                                    break
                    cols_to_drop.add(c)

            # 6. Drop empty data columns
            for c in range(num_cols):
                if c in cols_to_drop:
                    continue
                data_cells = [
                    padded[r][c].strip()
                    for r in range(header_count, len(padded))
                    if not _is_section_header(padded[r])
                    and padded[r][c].strip()
                ]
                if not data_cells:
                    for r_hdr in range(len(padded)):
                        if r_hdr < header_count or _is_section_header(
                            padded[r_hdr]
                        ):
                            h = padded[r_hdr][c].strip()
                            if h:
                                for next_c in range(c + 1, num_cols):
                                    if any(
                                        padded[dr][next_c].strip()
                                        for dr in range(
                                            header_count, len(padded)
                                        )
                                        if not _is_section_header(padded[dr])
                                    ):
                                        if not padded[r_hdr][next_c].strip():
                                            padded[r_hdr][next_c] = h
                                        break
                    cols_to_drop.add(c)

            clean_grid = []
            for r in range(len(padded)):
                row = []
                for c in range(num_cols):
                    if c not in cols_to_drop:
                        val = padded[r][c].strip()
                        val = _RE_PAREN_SPACES.sub(r"(\1)", val)
                        val = re.sub(
                            r"^\$\s*\(?\s*([0-9\.\,]+)\s*\)?",
                            r"$(\1)" if "(" in val and ")" in val else r"$\1",
                            val,
                        )
                        row.append(val)
                clean_grid.append(row)

            if not clean_grid or len(clean_grid[0]) <= 1:
                table.unwrap()
                continue

            # 3. Detect header rows: cutoff before first real data row (ignoring year headers)
            header_count = 1
            for i, r in enumerate(clean_grid):
                non_empty = [c for c in r if c.strip()]
                non_year_numbers = sum(
                    1
                    for c in non_empty
                    if (
                        _RE_NUMERIC_CELL.match(c)
                        or c in ("—", "-", "–", "*", "$—", "—*", "-*", "—)", "-)")
                    )
                    and not re_year.match(c)
                )
                ratio = (
                    (non_year_numbers / len(non_empty)) if non_empty else 0
                )
                if ratio >= 0.30:
                    header_count = i
                    break

            # If header_count is 0, synthesize blank header row
            if header_count == 0:
                header_count = 1
                clean_grid.insert(0, [""] * len(clean_grid[0]))

            try:
                converter = HTMLTableConverter(
                    grid=clean_grid, title="", header_row_count=header_count
                )
                table_text = converter.to_generic_table().build()
                pre_tag = soup.new_tag("pre")
                pre_tag.string = f"\n{table_text}\n"
                table.replace_with(pre_tag)
            except (ValueError, TypeError, KeyError, AttributeError):
                table.unwrap()

        return soup.get_text(separator="\n")

    def _detect_header_rows(self, rows: list[list[str]], table_soup: Any) -> int:
        """Detect number of header rows using multi-tier priority hierarchy."""
        if not rows:
            return 0

        trs = [tr for tr in table_soup.find_all("tr") if tr.get_text(strip=True)]
        if not trs:
            return 0

        def validate_count(count: int, allow_all: bool = False) -> int | None:
            if count <= 0:
                return None
            if count >= len(trs):
                return count if allow_all else None
            first_data_tr = trs[count]
            first_cell = first_data_tr.find(["td", "th"])
            if first_cell and first_cell.get_text(strip=True):
                return count
            return None

        # Priority 1: Explicit <th> tags
        th_count = 0
        for tr in trs:
            if tr.find("th"):
                th_count += 1
            else:
                break
        res = validate_count(th_count, allow_all=True)
        if res is not None:
            return res

        # Priority 2: CSS Border-based detection
        border_count = self._detect_by_border(trs, rows)
        res = validate_count(border_count)
        if res is not None:
            return res

        # Priority 3: Bold style density (> 50% of cells bold)
        bold_count = 0
        for tr in trs:
            cells = tr.find_all(["td", "th"])
            non_empty = [c for c in cells if c.get_text(strip=True)]
            bold_cells = [
                c
                for c in non_empty
                if c.find(["b", "strong"]) or _RE_BOLD_FONT.search(c.get("style", ""))
            ]
            if non_empty and (len(bold_cells) / len(non_empty)) > 0.5:
                bold_count += 1
            else:
                break
        res = validate_count(bold_count)
        if res is not None:
            return res

        # Priority 4: Underline style detection
        underline_count = 0
        for i in range(min(len(trs), 5)):
            tr = trs[i]
            has_u = tr.find("u") or any(
                _RE_UNDERLINE.search(c.get("style", ""))
                for c in tr.find_all(["td", "th"])
            )
            if has_u:
                underline_count = i + 1
        res = validate_count(underline_count)
        if res is not None:
            return res

        # Priority 5: Fallback default
        return 1

    def _detect_by_border(self, trs: list[Any], rows: list[list[str]]) -> int:
        """Detect header row boundary from border-top or border-bottom transitions."""
        if not trs or not rows:
            return 0

        transitions: list[tuple[int, str]] = []
        for idx, tr in enumerate(trs):
            cells = tr.find_all(["td", "th"])
            has_top = any(_RE_BORDER_TOP.search(c.get("style", "")) for c in cells)
            has_bottom = any(
                _RE_BORDER_BOTTOM.search(c.get("style", "")) for c in cells
            )
            if has_top:
                transitions.append((idx, "border_top"))
            if has_bottom:
                transitions.append((idx, "border_bottom"))

        if not transitions:
            return 0

        first_row, first_type = transitions[0]
        if first_type == "border_bottom":
            return first_row + 1
        if first_type == "border_top":
            return first_row
        return 0

    def _normalize_headers(self, text: str) -> str:
        """Standardize SEC Part and Item headings."""

        def _replace_part(m: re.Match[str]) -> str:
            part_name = m.group(1).upper()
            return f"\n\n{part_name}\n"

        def _replace_item(m: re.Match[str]) -> str:
            item_tag = m.group(1).upper()
            item_title = m.group(2).strip()
            if item_title:
                return f"\n\n{item_tag}. {item_title}\n"
            return f"\n\n{item_tag}.\n"

        text = _RE_PART_HEADER.sub(_replace_part, text)
        text = _RE_ITEM_HEADER.sub(_replace_item, text)
        return text
