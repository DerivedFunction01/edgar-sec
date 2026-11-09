"""Pure HTML transformation: SEC browse-edgar series page to typed rows.

Records live in this module beside `parser_idx`'s row model; ids come from
the ``CIK=S000…`` / ``CIK=C000…`` link hrefs, and an un-tickered class is a
row whose symbol cell is absent — never an empty string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from edgar_sec.domain.sec_urls import normalize_cik
from edgar_sec.engine.document.html.tree import FastHtmlNode, parse_html
from edgar_sec.foundation.hashing import sha256_bytes

__all__ = [
    "PARSER_FINGERPRINT",
    "BrowseClassRow",
    "BrowseDiagnostic",
    "BrowseDiagnostics",
    "BrowsePageInput",
    "BrowseParseFailure",
    "BrowseParseOutcome",
    "BrowseSeriesRow",
    "ParsedBrowseSeriesPage",
    "UnrecognizedBrowsePage",
    "parse_browse_series_page",
]

PARSER_FINGERPRINT = "browse-series-v2"

_DIAGNOSTIC_LIMIT = 32
_DETAIL_LIMIT = 256
_HEADING_RE = re.compile(r"Series for CIK = (\d+)")
_ITEMS_RE = re.compile(r"Items\s+(\d+)\s*-\s*(\d+)")
_SERIES_ID_RE = re.compile(r"S\d{9}")
_CLASS_ID_RE = re.compile(r"C\d{9}")


@dataclass(frozen=True, slots=True)
class BrowsePageInput:
    """One captured series page: the registrant it was fetched for."""

    cik: str
    source_url: str
    response_bytes: bytes


@dataclass(frozen=True, slots=True)
class BrowseSeriesRow:
    """One series on the page, as served."""

    series_id: str
    series_name: str


@dataclass(frozen=True, slots=True)
class BrowseClassRow:
    """One class under its series; ``symbol`` is None when un-tickered."""

    series_id: str
    class_id: str
    class_name: str
    symbol: str | None


@dataclass(frozen=True, slots=True)
class BrowseDiagnostic:
    """One named parse finding; a parsed page carries none."""

    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class BrowseDiagnostics:
    """The bounded diagnostic set of one parse."""

    items: tuple[BrowseDiagnostic, ...]
    suppressed_count: int = 0


@dataclass(frozen=True, slots=True)
class ParsedBrowseSeriesPage:
    """A series page parsed exactly: counts reconcile with its header."""

    cik: str
    source_url: str
    page_sha256: str
    registrant_name: str
    declared_item_count: int
    series: tuple[BrowseSeriesRow, ...]
    classes: tuple[BrowseClassRow, ...]
    diagnostics: BrowseDiagnostics


@dataclass(frozen=True, slots=True)
class UnrecognizedBrowsePage:
    """The payload is not a browse-edgar series page at all."""

    cik: str
    source_url: str
    page_sha256: str
    diagnostics: BrowseDiagnostics


@dataclass(frozen=True, slots=True)
class BrowseParseFailure:
    """A series page whose shape drifted; no partial rows are served."""

    cik: str
    source_url: str
    page_sha256: str
    diagnostics: BrowseDiagnostics


BrowseParseOutcome = (
    ParsedBrowseSeriesPage | UnrecognizedBrowsePage | BrowseParseFailure
)


def parse_browse_series_page(page: BrowsePageInput) -> BrowseParseOutcome:
    """Parse one captured series page without network access."""
    expected_cik = _expected_cik(page.cik)
    digest = sha256_bytes(page.response_bytes)
    diagnostics = _DiagnosticCollector()
    try:
        source = page.response_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        diagnostics.add("unsupported_encoding", str(exc))
        return BrowseParseFailure(
            expected_cik, page.source_url, digest, diagnostics.freeze()
        )

    tree = parse_html(source)
    page_cik = _page_cik(tree)
    if page_cik is None:
        diagnostics.add("missing_series_heading", "no Series for CIK heading")
        return UnrecognizedBrowsePage(
            expected_cik, page.source_url, digest, diagnostics.freeze()
        )
    if page_cik != expected_cik:
        diagnostics.add(
            "cik_mismatch", f"page serves {page_cik}, expected {expected_cik}"
        )
        return BrowseParseFailure(
            expected_cik, page.source_url, digest, diagnostics.freeze()
        )
    table = _results_table(tree)
    if table is None:
        diagnostics.add("missing_results_table", "no series results table")
        return UnrecognizedBrowsePage(
            expected_cik, page.source_url, digest, diagnostics.freeze()
        )

    declared = _declared_item_count(source)
    if declared is None:
        diagnostics.add("missing_items_header", "no Items range above the table")

    walker = _RowWalker(page_cik, diagnostics)
    for row in table.find_all("tr"):
        walker.walk(row)
    series, classes = walker.finish()
    if declared is not None and declared != len(series) + len(classes):
        diagnostics.add(
            "item_count_mismatch",
            f"header declares {declared}, parsed {len(series) + len(classes)}",
        )
    frozen = diagnostics.freeze()
    if frozen.items:
        return BrowseParseFailure(expected_cik, page.source_url, digest, frozen)
    return ParsedBrowseSeriesPage(
        cik=page_cik,
        source_url=page.source_url,
        page_sha256=digest,
        registrant_name=walker.registrant_name or "",
        declared_item_count=declared or 0,
        series=series,
        classes=classes,
        diagnostics=frozen,
    )


def _expected_cik(cik: str) -> str:
    text = cik.strip()
    if not text or not text.isascii() or not text.isdigit():
        raise ValueError(f"browse page CIK is not numeric: {cik!r}")
    return normalize_cik(text)


def _page_cik(tree: FastHtmlNode) -> str | None:
    for heading in tree.find_all("h4"):
        match = _HEADING_RE.search(heading.text())
        if match is not None:
            return normalize_cik(match.group(1))
    return None


def _declared_item_count(source: str) -> int | None:
    match = _ITEMS_RE.search(source)
    if match is None or int(match.group(1)) != 1:
        return None
    return int(match.group(2))


def _results_table(tree: FastHtmlNode) -> FastHtmlNode | None:
    for table in tree.find_all("table"):
        for anchor in table.find_all("a"):
            cik_param, scd = _link_params(anchor)
            if scd == "filings" and (
                _SERIES_ID_RE.fullmatch(cik_param or "")
                or _CLASS_ID_RE.fullmatch(cik_param or "")
            ):
                return table
    return None


def _link_params(anchor: FastHtmlNode) -> tuple[str | None, str]:
    href = anchor.get("href") or ""
    query = parse_qs(urlsplit(href).query)
    cik_values = query.get("CIK")
    scd_values = query.get("scd")
    return (
        cik_values[0] if cik_values else None,
        scd_values[0] if scd_values else "",
    )


def _text(node: FastHtmlNode) -> str:
    return " ".join(node.text().split())


def _direct_cells(row: FastHtmlNode) -> tuple[FastHtmlNode, ...]:
    cells = []
    child = row.raw_node.child
    while child is not None:
        if child.tag in {"th", "td"}:
            cells.append(FastHtmlNode(child))
        child = child.next
    return tuple(cells)


class _DiagnosticCollector:
    __slots__ = ("items", "suppressed_count")

    def __init__(self) -> None:
        self.items: list[BrowseDiagnostic] = []
        self.suppressed_count = 0

    def add(self, code: str, detail: str) -> None:
        if len(self.items) == _DIAGNOSTIC_LIMIT:
            self.suppressed_count += 1
            return
        self.items.append(
            BrowseDiagnostic(code, " ".join(detail.split())[:_DETAIL_LIMIT])
        )

    def freeze(self) -> BrowseDiagnostics:
        return BrowseDiagnostics(tuple(self.items), self.suppressed_count)


@dataclass(frozen=True, slots=True)
class _Anchor:
    cell_index: int
    cik_param: str
    scd: str
    text: str


class _RowWalker:
    """Document-order walk: registrant, then series with their classes."""

    __slots__ = (
        "cik",
        "diagnostics",
        "registrant_name",
        "series",
        "classes",
        "_series_ids",
        "_class_keys",
        "_class_first",
        "_current_series",
    )

    def __init__(self, cik: str, diagnostics: _DiagnosticCollector) -> None:
        self.cik = cik
        self.diagnostics = diagnostics
        self.registrant_name: str | None = None
        self.series: list[BrowseSeriesRow] = []
        self.classes: list[BrowseClassRow] = []
        self._series_ids: set[str] = set()
        self._class_keys: set[tuple[str, str]] = set()
        self._class_first: dict[str, tuple[str, str, str | None]] = {}
        self._current_series: str | None = None

    def walk(self, row: FastHtmlNode) -> None:
        cells = _direct_cells(row)
        anchors: list[_Anchor] = []
        for index, cell in enumerate(cells):
            anchor = cell.find("a")
            if anchor is None:
                continue
            cik_param, scd = _link_params(anchor)
            if cik_param is not None:
                anchors.append(_Anchor(index, cik_param, scd, _text(anchor)))
        if not anchors:
            return
        filings = [a for a in anchors if a.scd == "filings"]
        if filings and _SERIES_ID_RE.fullmatch(filings[0].cik_param):
            self._series_row(cells, anchors, filings[0])
        elif filings and _CLASS_ID_RE.fullmatch(filings[0].cik_param):
            self._class_row(cells, anchors, filings[0])
        elif all(a.cik_param == self.cik for a in anchors):
            self._registrant_row(anchors)
        else:
            self.diagnostics.add(
                "unrecognized_row",
                ", ".join(f"{a.cik_param}/{a.scd}" for a in anchors),
            )

    def finish(
        self,
    ) -> tuple[tuple[BrowseSeriesRow, ...], tuple[BrowseClassRow, ...]]:
        if self.registrant_name is None:
            self.diagnostics.add(
                "missing_registrant_row", "no registrant row above the series"
            )
        return tuple(self.series), tuple(self.classes)

    def _registrant_row(self, anchors: list[_Anchor]) -> None:
        if self.registrant_name is not None:
            self.diagnostics.add(
                "duplicate_registrant_row", "second registrant row on the page"
            )
            return
        names = [a for a in anchors if a.scd == "series"]
        if len(names) != 1:
            self.diagnostics.add(
                "missing_registrant_name", "registrant row has no name link"
            )
            return
        self.registrant_name = names[0].text

    def _series_row(
        self, cells: tuple[FastHtmlNode, ...], anchors: list[_Anchor], filing: _Anchor
    ) -> None:
        series_id = filing.cik_param
        if filing.text != series_id:
            self.diagnostics.add(
                "id_text_mismatch", f"link text {filing.text} != {series_id}"
            )
        names = [a for a in anchors if a.scd == "series" and a.cik_param == series_id]
        if len(anchors) != 2 or len(names) != 1:
            self.diagnostics.add("missing_series_name", f"{series_id} has no name link")
            return
        if series_id in self._series_ids:
            self.diagnostics.add("duplicate_series_id", series_id)
            return
        self._series_ids.add(series_id)
        self.series.append(BrowseSeriesRow(series_id, names[0].text))
        self._current_series = series_id

    def _class_row(
        self, cells: tuple[FastHtmlNode, ...], anchors: list[_Anchor], filing: _Anchor
    ) -> None:
        class_id = filing.cik_param
        if filing.text != class_id:
            self.diagnostics.add(
                "id_text_mismatch", f"link text {filing.text} != {class_id}"
            )
        if len(anchors) != 1:
            self.diagnostics.add(
                "unrecognized_row", f"{class_id} row carries extra links"
            )
            return
        if self._current_series is None:
            self.diagnostics.add(
                "class_before_series", f"{class_id} precedes any series row"
            )
            return
        name_index = filing.cell_index + 1
        if name_index >= len(cells):
            self.diagnostics.add("missing_class_name", class_id)
            return
        class_name = _text(cells[name_index])
        symbol: str | None = None
        symbol_index = name_index + 1
        if symbol_index < len(cells):
            symbol_text = _text(cells[symbol_index])
            if not symbol_text:
                self.diagnostics.add(
                    "empty_symbol_cell",
                    f"{class_id} has a present but blank symbol cell",
                )
                return
            symbol = symbol_text
        if len(cells) > symbol_index + 1:
            self.diagnostics.add(
                "unexpected_cells", f"{class_id} row has trailing cells"
            )
            return
        key = (self._current_series, class_id)
        if key in self._class_keys:
            self.diagnostics.add("duplicate_class_id", class_id)
            return
        first = self._class_first.get(class_id)
        if first is not None and (first[1], first[2]) != (class_name, symbol):
            self.diagnostics.add(
                "duplicate_class_id",
                f"{class_id} listed under {first[0]} and "
                f"{self._current_series} with a differing name or symbol",
            )
            return
        self._class_keys.add(key)
        if first is None:
            self._class_first[class_id] = (
                self._current_series,
                class_name,
                symbol,
            )
        self.classes.append(
            BrowseClassRow(self._current_series, class_id, class_name, symbol)
        )
