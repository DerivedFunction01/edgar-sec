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

        # 1. If HTML table structures exist, extract and align tables
        if "<table" in text.lower():
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
        tables = soup.find_all("table")
        for table in tables:
            rows: list[list[str]] = []
            col_count = 0

            # Process each <tr>
            try:
                for tr in table.find_all("tr"):
                    if not tr.get_text(strip=True):
                        continue

                    row_cells: list[str] = []
                    for cell in tr.find_all(["td", "th"]):
                        cell_text = cell.get_text(separator=" ", strip=True)
                        try:
                            colspan = int(cell.get("colspan", 1))
                        except (ValueError, TypeError):
                            colspan = 1

                        row_cells.append(cell_text)
                        if colspan > 1:
                            row_cells.extend([""] * (colspan - 1))

                    if row_cells:
                        rows.append(row_cells)
                        col_count = max(col_count, len(row_cells))
            except (ValueError, TypeError, KeyError, AttributeError):
                table.unwrap()
                continue

            # Second-pass: trim completely empty spacer columns and empty rows
            if rows and col_count > 1:
                for r in rows:
                    if len(r) < col_count:
                        r.extend([""] * (col_count - len(r)))

                non_empty_cols = [
                    c for c in range(col_count) if any(bool(r[c].strip()) for r in rows)
                ]
                if non_empty_cols:
                    rows = [[r[c] for c in non_empty_cols] for r in rows]
                    rows = [r for r in rows if any(bool(cell.strip()) for cell in r)]
                    col_count = len(non_empty_cols)

            # Detect header rows using multi-tier hierarchy
            header_count = self._detect_header_rows(rows, table)

            # Convert multi-row/col data tables to ASCII grid; unwrap layout tables
            if len(rows) > 1 and col_count > 1:
                try:
                    converter = HTMLTableConverter(
                        grid=rows, title="", header_row_count=header_count
                    )
                    table_text = converter.to_generic_table().build()
                    pre_tag = soup.new_tag("pre")
                    pre_tag.string = f"\n{table_text}\n"
                    table.replace_with(pre_tag)
                except (ValueError, TypeError, KeyError, AttributeError):
                    table.unwrap()
            else:
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
