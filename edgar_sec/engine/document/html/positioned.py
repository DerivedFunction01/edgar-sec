"""Spatial reconstruction for filings typeset as positioned fragments.
Detection is purely structural: inline ``position:absolute`` plus numeric
``left``/``top`` coordinates, in a document with no native tables.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass

from edgar_sec.engine.document.html.tags import BLOCK_TAGS
from edgar_sec.engine.document.html.tree import FastHtmlNode, parse_html

_RE_TABLE_TAG = re.compile(r"<table\b", re.IGNORECASE)
_RE_ANY_TAG = re.compile(r"<(/?)([a-zA-Z][\w:-]*)\b[^>]*?(/?)>", re.DOTALL)
_RE_STYLE_ATTR = re.compile(r"""style\s*=\s*(["'])(.*?)\1""", re.IGNORECASE | re.DOTALL)
_RE_PAGE_CONTAINER_OPEN = re.compile(
    r"<div\b[^>]*style\s*=\s*([\"'])(?:(?!\1).)*?"
    r"position\s*:\s*relative(?:(?!\1).)*?(?:page-break-after|break-after)"
    r"(?:(?!\1).)*?\1[^>]*>",
    re.IGNORECASE | re.DOTALL,
)
_RE_COORDINATE = re.compile(r"^(-?[\d.]+)(px|pt)?$", re.IGNORECASE)
_RE_WHITESPACE_RUN = re.compile(r"\s+")

_PT_TO_PX = 96.0 / 72.0
_MIN_DOCUMENT_FRAGMENTS = 20
_MIN_POSITIONED_TEXT_SHARE = 0.5
_MIN_ELIGIBLE_SHARE = 0.5


@dataclass(frozen=True)
class PositionedFragment:
    """One positioned element's text at its page coordinates."""

    top: float
    left: float
    text: str


@dataclass(frozen=True)
class PositionedPage:
    """The positioned fragments of one printed page, in document order."""

    fragments: tuple[PositionedFragment, ...]


def _style_properties(style: str) -> dict[str, str]:
    properties: dict[str, str] = {}
    for declaration in style.split(";"):
        name, separator, value = declaration.partition(":")
        if separator:
            properties[name.strip().lower()] = value.strip().lower()
    return properties


def _coordinate(value: str | None) -> float | None:
    """Parse one px/pt coordinate; any other unit or form is ineligible."""
    if value is None:
        return None
    match = _RE_COORDINATE.match(value.strip())
    if match is None:
        return None
    amount = float(match.group(1))
    if (match.group(2) or "px").lower() == "pt":
        return amount * _PT_TO_PX
    return amount


def _fragment_coordinates(node: FastHtmlNode) -> tuple[float, float] | None:
    """Return ``(top, left)`` when the node is an eligible positioned fragment."""
    style = node.attributes.get("style")
    if not style:
        return None
    properties = _style_properties(style)
    if properties.get("position") != "absolute":
        return None
    left = _coordinate(properties.get("left"))
    top = _coordinate(properties.get("top"))
    if left is None or top is None:
        return None
    return (top, left)


def _page_coordinates(node: FastHtmlNode) -> tuple[float, float] | None:
    """Own coordinates plus every positioned ancestor's offset.
    A fragment inside a positioned wrapper is placed relative to that
    wrapper, so its page position is the sum over the ancestor chain.
    """
    coordinates = _fragment_coordinates(node)
    if coordinates is None:
        return None
    top, left = coordinates
    ancestor = node.parent
    while ancestor is not None:
        style = ancestor.attributes.get("style")
        if style:
            properties = _style_properties(style)
            if properties.get("position") in ("absolute", "relative"):
                top += _coordinate(properties.get("top")) or 0.0
                left += _coordinate(properties.get("left")) or 0.0
        ancestor = ancestor.parent
    return (top, left)


def _is_page_container(node: FastHtmlNode) -> bool:
    style = node.attributes.get("style")
    if not style:
        return False
    properties = _style_properties(style)
    if properties.get("position") != "relative":
        return False
    return "page-break-after" in properties or "break-after" in properties


def _raw_coordinates(node: object) -> tuple[float, float] | None:
    attributes = getattr(node, "attributes", None)
    if not attributes:
        return None
    style = attributes.get("style")
    if not style:
        return None
    properties = _style_properties(str(style))
    if properties.get("position") != "absolute":
        return None
    left = _coordinate(properties.get("left"))
    top = _coordinate(properties.get("top"))
    if left is None or top is None:
        return None
    return (top, left)


def _residual_text(node: FastHtmlNode) -> str:
    """The node's text excluding positioned descendants' subtrees.
    A positioned wrapper's text is exactly its children's; only the residual
    is the node's own fragment text.
    """
    chunks: list[str] = []

    def separate() -> None:
        if chunks and not chunks[-1].endswith((" ", "\n", "\t", "\xa0")):
            chunks.append(" ")

    def walk(raw: object) -> None:
        for child in raw.iter(include_text=True):  # type: ignore[attr-defined]
            tag = child.tag
            if tag == "-text":
                chunks.append(child.text(deep=False))
            elif tag == "br":
                chunks.append(" ")
            elif _raw_coordinates(child) is not None:
                continue
            elif tag in BLOCK_TAGS:
                separate()
                walk(child)
                separate()
            else:
                walk(child)

    walk(node.raw_node)
    return _RE_WHITESPACE_RUN.sub(" ", "".join(chunks)).strip()


def _collect_fragments(
    tree_nodes: list[FastHtmlNode],
) -> list[tuple[FastHtmlNode, PositionedFragment]]:
    """Eligible fragments with non-empty residual text, in document order."""
    collected: list[tuple[FastHtmlNode, PositionedFragment]] = []
    for node in tree_nodes:
        coordinates = _page_coordinates(node)
        if coordinates is None:
            continue
        text = _residual_text(node)
        if not text:
            continue
        collected.append(
            (
                node,
                PositionedFragment(top=coordinates[0], left=coordinates[1], text=text),
            )
        )
    return collected


def _census(html: str) -> tuple[int, int]:
    """Count absolutely-positioned elements and their coordinate-eligible share."""
    absolute = 0
    eligible = 0
    for match in _RE_STYLE_ATTR.finditer(html):
        properties = _style_properties(match.group(2))
        if properties.get("position") != "absolute":
            continue
        absolute += 1
        if (
            _coordinate(properties.get("left")) is not None
            and _coordinate(properties.get("top")) is not None
        ):
            eligible += 1
    return absolute, eligible


def extract_positioned_pages(html: str) -> tuple[PositionedPage, ...]:
    """Extract positioned fragments grouped by printed page.
    Pages are the sentinel-delimited segments when present, else page
    containers; fragments nested inside another fragment are skipped.
    """
    from edgar_sec.engine.document.html.breaks import PAGE_SPLIT_SENTINEL

    if PAGE_SPLIT_SENTINEL in html:
        groups: list[list[PositionedFragment]] = []
        for segment in html.split(PAGE_SPLIT_SENTINEL):
            fragments = _extract_segment_fragments(segment)
            if fragments:
                groups.append(fragments)
        return tuple(PositionedPage(tuple(group)) for group in groups)
    return _extract_pages_by_container(html)


def _extract_segment_fragments(segment: str) -> list[PositionedFragment]:
    fragments, _ = _segment_data(segment)
    return fragments


def _segment_data(segment: str) -> tuple[list[PositionedFragment], int]:
    """A segment's deduped fragments and its eligible-element count."""
    if "absolute" not in segment:
        return [], 0
    nodes = list(parse_html(segment).traverse())
    eligible = sum(1 for node in nodes if _fragment_coordinates(node) is not None)
    fragments: list[PositionedFragment] = []
    seen: set[tuple[float, float, str]] = set()
    for _, fragment in _collect_fragments(nodes):
        key = (fragment.top, fragment.left, fragment.text)
        if key in seen:
            continue
        seen.add(key)
        fragments.append(fragment)
    return fragments, eligible


def _extract_pages_by_container(html: str) -> tuple[PositionedPage, ...]:
    tree = parse_html(html)
    groups: list[list[PositionedFragment]] = []
    group_index: dict[int, int] = {}
    seen_by_group: dict[int, set[tuple[float, float, str]]] = {}
    for node, fragment in _collect_fragments(list(tree.traverse())):
        container = node.parent
        while container is not None and not _is_page_container(container):
            container = container.parent
        key = hash(container.raw_node) if container is not None else 0
        if key not in group_index:
            group_index[key] = len(groups)
            groups.append([])
            seen_by_group[key] = set()
        dedupe_key = (fragment.top, fragment.left, fragment.text)
        if dedupe_key in seen_by_group[key]:
            continue
        seen_by_group[key].add(dedupe_key)
        groups[group_index[key]].append(fragment)
    return tuple(PositionedPage(tuple(group)) for group in groups if group)


@dataclass(frozen=True)
class PositionedRow:
    """Fragments sharing one printed line, ordered by ``left``."""

    top: float
    fragments: tuple[PositionedFragment, ...]


@dataclass(frozen=True)
class TableBand:
    """A run of tabular rows; each row is label cell plus one cell per column."""

    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class FlowLine:
    """One non-tabular printed line."""

    text: str


PageBlock = TableBand | FlowLine

_RE_NUMERIC_FRAGMENT = re.compile(r"^\$?\s?\(?-?\d[\d,]*(\.\d+)?\)?\s?%?$")
_DASH_FRAGMENTS = frozenset({"-", "—", "–"})
_MAX_PITCH_DELTA = 60.0
_TABULAR_SPAN = 150.0


def _is_value_fragment(fragment: PositionedFragment) -> bool:
    return bool(_RE_NUMERIC_FRAGMENT.match(fragment.text)) or (
        fragment.text in _DASH_FRAGMENTS
    )


def _page_pitch(fragments: tuple[PositionedFragment, ...]) -> float:
    tops = sorted({fragment.top for fragment in fragments})
    deltas = [
        later - earlier
        for earlier, later in zip(tops, tops[1:])
        if 0 < later - earlier <= _MAX_PITCH_DELTA
    ]
    if not deltas:
        return 0.0
    deltas.sort()
    return deltas[len(deltas) // 4]


def cluster_page_rows(page: PositionedPage) -> tuple[PositionedRow, ...]:
    """Cluster a page's fragments into printed rows.
    Rows chain over distinct tops within a pitch-derived tolerance; a
    label-only row one pitch below a valued row joins that row's label.
    """
    if not page.fragments:
        return ()
    pitch = _page_pitch(page.fragments)
    tolerance = max(pitch / 3, 2.0)
    tops = sorted({fragment.top for fragment in page.fragments})
    clusters: list[list[float]] = [[tops[0]]]
    for top in tops[1:]:
        if top - clusters[-1][-1] <= tolerance:
            clusters[-1].append(top)
        else:
            clusters.append([top])
    cluster_of = {top: i for i, cluster in enumerate(clusters) for top in cluster}
    grouped: dict[int, list[PositionedFragment]] = {}
    for fragment in page.fragments:
        grouped.setdefault(cluster_of[fragment.top], []).append(fragment)
    rows = [
        PositionedRow(
            top=clusters[i][0],
            fragments=tuple(sorted(grouped[i], key=lambda f: f.left)),
        )
        for i in sorted(grouped)
    ]
    return tuple(_merge_label_continuations(rows, pitch))


def _starts_lowercase(fragment: PositionedFragment) -> bool:
    return fragment.text[:1].islower()


def _label_text(row: PositionedRow) -> str:
    return " ".join(
        f.text for f in _merge_symbols(row.fragments) if not _is_value_fragment(f)
    )


def _with_label(row: PositionedRow, label_text: str) -> PositionedRow:
    fragments = _merge_symbols(row.fragments)
    labels = [f for f in fragments if not _is_value_fragment(f)]
    values = [f for f in fragments if _is_value_fragment(f)]
    anchor = labels[0] if labels else row.fragments[0]
    combined = PositionedFragment(top=row.top, left=anchor.left, text=label_text)
    return PositionedRow(
        top=row.top,
        fragments=tuple(sorted([combined, *values], key=lambda f: f.left)),
    )


def _merge_label_continuations(
    rows: list[PositionedRow], pitch: float
) -> list[PositionedRow]:
    """Join wrapped labels split across two printed lines.
    Values may sit on either line; the valueless line joins the valued one.
    The continuation line must start lowercase, or it is a section heading.
    """
    if pitch <= 0:
        return rows
    merged: list[PositionedRow] = []
    pending_label: list[str] = []
    pending_top = 0.0
    for index, row in enumerate(rows):
        label_only = not any(_is_value_fragment(f) for f in row.fragments)
        if label_only and row.fragments:
            following = rows[index + 1] if index + 1 < len(rows) else None
            previous_values = (
                [f for f in merged[-1].fragments if _is_value_fragment(f)]
                if merged
                else []
            )
            if (
                merged
                and _starts_lowercase(row.fragments[0])
                and row.top - merged[-1].top <= 1.6 * pitch
                and previous_values
                and all(
                    f.left < min(v.left for v in previous_values) for f in row.fragments
                )
            ):
                previous = merged[-1]
                merged[-1] = _with_label(
                    previous,
                    " ".join(
                        filter(
                            None,
                            [_label_text(previous), *(f.text for f in row.fragments)],
                        )
                    ),
                )
                continue
            if (
                following is not None
                and row.top - (pending_top if pending_label else row.top) <= 1.6 * pitch
                and following.top - row.top <= 1.6 * pitch
                and any(_is_value_fragment(f) for f in following.fragments)
                and _starts_lowercase(
                    next(
                        (f for f in following.fragments if not _is_value_fragment(f)),
                        following.fragments[0],
                    )
                )
            ):
                if not pending_label:
                    pending_top = row.top
                pending_label.extend(f.text for f in row.fragments)
                continue
        if pending_label:
            row = _with_label(row, " ".join([*pending_label, _label_text(row)]))
            pending_label = []
        merged.append(row)
    return merged


def _estimate_char_width(rows: tuple[PositionedRow, ...]) -> float:
    """Estimate the page's character width from same-column value pairs.
    Values are right-aligned, so two values of different lengths in one
    column imply the width from their left and length difference.
    """
    values = [
        fragment
        for row in rows
        for fragment in row.fragments
        if _is_value_fragment(fragment) and len(fragment.text) >= 4
    ]
    candidates: list[float] = []
    for i, first in enumerate(values):
        for second in values[i + 1 :]:
            length_gap = len(first.text) - len(second.text)
            if abs(length_gap) < 2:
                continue
            width = (second.left - first.left) / length_gap
            if 4.0 <= width <= 14.0:
                candidates.append(width)
    if not candidates:
        return 7.0
    candidates.sort()
    return candidates[len(candidates) // 2]


def _right_edge(fragment: PositionedFragment, char_width: float) -> float:
    """Right edge of a value fragment, discounting merged ``$``/``%`` symbols."""
    length = len(fragment.text)
    if fragment.text.startswith("$ "):
        length -= 2
    if fragment.text.endswith(" %"):
        length -= 2
    return fragment.left + length * char_width


def _column_anchors(rows: tuple[PositionedRow, ...], char_width: float) -> list[float]:
    """Cluster value fragments' right edges into column anchors.
    A cluster supported by a single fragment (a centered header year, say)
    is dropped when any cluster recurs, since real columns repeat per row.
    """
    tolerance = max(6.0, 1.3 * char_width)
    rights = sorted(
        _right_edge(fragment, char_width)
        for row in rows
        for fragment in row.fragments
        if _is_value_fragment(fragment)
    )
    clusters: list[list[float]] = []
    for right in rights:
        if clusters and right - clusters[-1][-1] <= tolerance:
            clusters[-1].append(right)
        else:
            clusters.append([right])
    if any(len(cluster) >= 2 for cluster in clusters):
        clusters = [cluster for cluster in clusters if len(cluster) >= 2]
    return [sum(cluster) / len(cluster) for cluster in clusters]


def _merge_symbols(
    fragments: tuple[PositionedFragment, ...],
) -> list[PositionedFragment]:
    """Attach ``$`` prefixes and ``%`` suffixes to their neighbouring value."""
    merged: list[PositionedFragment] = []
    pending: list[PositionedFragment] = []
    for fragment in fragments:
        if fragment.text == "$":
            pending.append(fragment)
            continue
        if fragment.text == "%" and merged and _is_value_fragment(merged[-1]):
            previous = merged[-1]
            merged[-1] = PositionedFragment(
                top=previous.top, left=previous.left, text=f"{previous.text} %"
            )
            continue
        if _is_value_fragment(fragment) and pending:
            prefix = " ".join(f.text for f in pending)
            merged.append(
                PositionedFragment(
                    top=fragment.top,
                    left=fragment.left,
                    text=f"{prefix} {fragment.text}",
                )
            )
            pending = []
            continue
        merged.extend(pending)
        pending = []
        merged.append(fragment)
    merged.extend(pending)
    return merged


def _row_cells(
    row: PositionedRow, anchors: list[float], char_width: float
) -> tuple[str, ...]:
    """Assign a row's fragments to the label cell and one cell per anchor."""
    cells: dict[int, list[tuple[float, str]]] = {}
    first_anchor = anchors[0] if anchors else float("inf")
    for fragment in _merge_symbols(row.fragments):
        right = _right_edge(fragment, char_width)
        if not _is_value_fragment(fragment) and fragment.left < first_anchor - 40:
            column = -1
        elif anchors:
            column = min(range(len(anchors)), key=lambda i: abs(anchors[i] - right))
        else:
            column = -1
        cells.setdefault(column, []).append((fragment.left, fragment.text))
    label = " ".join(text for _, text in sorted(cells.get(-1, [])))
    return tuple(
        [label]
        + [
            " ".join(text for _, text in sorted(cells.get(i, [])))
            for i in range(len(anchors))
        ]
    )


_CHECKBOX_FRAGMENTS = frozenset({"☐", "☑"})


def _looks_like_prose(text: str) -> bool:
    return (
        len(text) >= 40
        and text.count(" ") >= 5
        and any(character.islower() for character in text)
    )


def _is_tabular_row(row: PositionedRow) -> bool:
    if sum(1 for f in row.fragments if _is_value_fragment(f)) >= 2:
        return True
    if len(row.fragments) < 2:
        return False
    lefts = [f.left for f in row.fragments]
    if max(lefts) - min(lefts) < _TABULAR_SPAN:
        return False
    if any(_is_value_fragment(fragment) for fragment in row.fragments):
        return True
    # A wide row with no value is prose when its joined text reads as a
    # sentence or a fragment is a cover checkbox: either lends the line a
    # table's span without a table's content.
    joined = " ".join(
        fragment.text
        for fragment in sorted(row.fragments, key=lambda fragment: fragment.left)
    )
    return not (
        _looks_like_prose(joined)
        or any(fragment.text in _CHECKBOX_FRAGMENTS for fragment in row.fragments)
    )


def layout_page(page: PositionedPage) -> tuple[PageBlock, ...]:
    """Lay a page out as table bands and flow lines."""
    rows = cluster_page_rows(page)
    if not rows:
        return ()
    char_width = _estimate_char_width(rows)
    blocks: list[PageBlock] = []
    band: list[PositionedRow] = []

    def flush_band() -> None:
        if band:
            anchors = _column_anchors(tuple(band), char_width)
            blocks.append(
                TableBand(
                    rows=tuple(_row_cells(row, anchors, char_width) for row in band)
                )
            )
            band.clear()

    for row in rows:
        if _is_tabular_row(row):
            band.append(row)
        else:
            flush_band()
            blocks.append(
                FlowLine(text=" ".join(f.text for f in _merge_symbols(row.fragments)))
            )
    flush_band()
    return tuple(blocks)


def _tag_coordinates(tag_text: str) -> tuple[float, float] | None:
    style = _RE_STYLE_ATTR.search(tag_text)
    if style is None:
        return None
    properties = _style_properties(style.group(2))
    if properties.get("position") != "absolute":
        return None
    left = _coordinate(properties.get("left"))
    top = _coordinate(properties.get("top"))
    if left is None or top is None:
        return None
    return (top, left)


def _eligible_spans(segment: str) -> list[tuple[int, int]]:
    """Source spans of every eligible positioned element.
    A span runs from the element's open tag to its matching close, found by
    depth counting over tags of the same name.
    """
    tags = list(_RE_ANY_TAG.finditer(segment))
    spans: list[tuple[int, int]] = []
    for index, tag in enumerate(tags):
        if tag.group(1) or tag.group(3):
            continue
        if _tag_coordinates(tag.group(0)) is None:
            continue
        name = tag.group(2).lower()
        depth = 1
        end = len(segment)
        for later in tags[index + 1 :]:
            if later.group(2).lower() != name:
                continue
            if later.group(1):
                depth -= 1
                if depth == 0:
                    end = later.end()
                    break
            elif not later.group(3):
                depth += 1
        spans.append((tag.start(), end))
    return spans


def _outermost_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    return sorted(
        span
        for span in spans
        if not any(
            other != span and other[0] <= span[0] and span[1] <= other[1]
            for other in spans
        )
    )


def _blocks_markup(blocks: tuple[PageBlock, ...]) -> str:
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, TableBand):
            rows = "".join(
                "<tr>"
                + "".join(
                    f"<td>{html_lib.escape(cell, quote=False)}</td>" for cell in row
                )
                + "</tr>"
                for row in block.rows
            )
            parts.append(f"<table>{rows}</table>")
        else:
            parts.append(f"<div>{html_lib.escape(block.text, quote=False)}</div>")
    return "".join(parts)


def _reconstruct_segment(segment: str) -> str:
    if "absolute" not in segment:
        return segment
    spans = _eligible_spans(segment)
    if not spans:
        return segment
    fragments, eligible = _segment_data(segment)
    if eligible != len(spans) or not fragments:
        return segment
    markup = _blocks_markup(layout_page(PositionedPage(tuple(fragments))))
    if not markup:
        return segment
    pieces: list[str] = []
    cursor = 0
    for index, (start, end) in enumerate(_outermost_spans(spans)):
        pieces.append(segment[cursor:start])
        if index == 0:
            pieces.append(markup)
        cursor = end
    pieces.append(segment[cursor:])
    return "".join(pieces)


def _split_segments(html: str) -> tuple[list[str], str]:
    """Split into per-page segments; returns the segments and the joiner."""
    from edgar_sec.engine.document.html.breaks import PAGE_SPLIT_SENTINEL

    if PAGE_SPLIT_SENTINEL in html:
        return html.split(PAGE_SPLIT_SENTINEL), PAGE_SPLIT_SENTINEL
    opens = [match.start() for match in _RE_PAGE_CONTAINER_OPEN.finditer(html)]
    if not opens:
        return [html], ""
    segments = [html[: opens[0]]]
    for index, start in enumerate(opens):
        end = opens[index + 1] if index + 1 < len(opens) else len(html)
        segments.append(html[start:end])
    return segments, ""


def reconstruct_positioned_html(html: str) -> str:
    """Replace positioned layout with synthetic tables and flow lines.
    Segments whose string spans disagree with the DOM census are left
    untouched, so a parse discrepancy degrades to today's rendering.
    """
    if "absolute" not in html:
        return html
    segments, joiner = _split_segments(html)
    rebuilt = [_reconstruct_segment(segment) for segment in segments]
    if rebuilt == segments:
        return html
    return joiner.join(rebuilt)


def detect_positioned_layout(html: str) -> bool:
    """Whether the document is positioned-dominant and reconstruction applies.
    Requires no native tables, a floor of eligible fragments forming the
    majority of positioned elements, and the majority of the document text.
    """
    if not html or _RE_TABLE_TAG.search(html):
        return False
    absolute, eligible = _census(html)
    if eligible < _MIN_DOCUMENT_FRAGMENTS:
        return False
    if eligible < absolute * _MIN_ELIGIBLE_SHARE:
        return False
    pages = extract_positioned_pages(html)
    fragment_chars = sum(
        len(fragment.text.replace(" ", ""))
        for page in pages
        for fragment in page.fragments
    )
    total_chars = len(_RE_WHITESPACE_RUN.sub("", parse_html(html).text()))
    if total_chars == 0:
        return False
    return fragment_chars >= total_chars * _MIN_POSITIONED_TEXT_SHARE


__all__ = [
    "FlowLine",
    "PageBlock",
    "PositionedFragment",
    "PositionedPage",
    "PositionedRow",
    "TableBand",
    "cluster_page_rows",
    "detect_positioned_layout",
    "extract_positioned_pages",
    "layout_page",
    "reconstruct_positioned_html",
]
