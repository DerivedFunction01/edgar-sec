"""Visible HTML page-marker analysis using DOM coordinates."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from defs.tables.tokens import is_numeric_cell

from .candidates import roman_to_int
from .constants import (
    _HIDDEN_STYLE_RE,
    _PAGE_BREAK_AVOID_RE,
    _PAGE_BREAK_RE,
    _RE_HIDDEN_TEMPLATE,
    _RE_LEADING_NUMBER,
    _RE_LETTER_NUMBER,
    _RE_PAGE_SEMANTIC,
    _RE_TOC_SEMANTIC,
    _RE_TRAILING_NUMBER,
    _VALUE_RE,
)
from .layout import candidate_template
from .models import (
    PageCandidate,
    PageMarker,
    PageMarkerAction,
    PageMarkerAnalysis,
    PageMarkerDecision,
    PageMarkerKind,
    PageMarkerTerminalState,
    PageNumberRun,
    TemplateEvidence,
)
from .pre import extract_ascii_pre
from .sequence import monotone_fraction, unify_alternating_runs


def _attrs(node: object) -> dict[str, Any]:
    value = getattr(node, "attrs", {})
    return value if isinstance(value, dict) else {}


def _attr_text(node: object) -> str:
    attrs = _attrs(node)
    values = [
        str(item)
        if not isinstance(item, (list, tuple))
        else " ".join(str(x) for x in item)
        for key in ("id", "class", "title", "data-page", "data-page-number")
        if (item := attrs.get(key, ""))
    ]
    return " ".join(values).casefold()


def _node_text(node: object) -> str:
    getter = getattr(node, "get_text", None)
    return str(getter(" ", strip=True)) if callable(getter) else ""


def _parent(node: object) -> object | None:
    value = getattr(node, "parent", None)
    return value if value is not node else None


def _hidden(node: object) -> bool:
    current: object | None = node
    while current is not None:
        attrs = _attrs(current)
        if "hidden" in attrs or str(attrs.get("aria-hidden", "")).casefold() == "true":
            return True
        if _HIDDEN_STYLE_RE.search(
            str(attrs.get("style", ""))
        ) or _RE_HIDDEN_TEMPLATE.search(_attr_text(current)):
            return True
        current = _parent(current)
    return False


def _semantic(node: object) -> bool:
    return bool(_RE_PAGE_SEMANTIC.search(_attr_text(node)))


def _toc_node(node: object) -> bool:
    current: object | None = node
    while current is not None:
        if _RE_TOC_SEMANTIC.search(_attr_text(current)):
            return True
        current = _parent(current)
    return False


def _actual_break(node: object) -> bool:
    current: object | None = node
    while current is not None:
        style = str(_attrs(current).get("style", ""))
        if _PAGE_BREAK_RE.search(style) and not _PAGE_BREAK_AVOID_RE.search(style):
            return True
        current = _parent(current)
    return False


def _parse_value(
    text: str, *, allow_letter_number: bool = True
) -> tuple[int, str, str] | None:
    cleaned = " ".join(text.split())
    match = _VALUE_RE.fullmatch(cleaned)
    if match is not None:
        value_text = match.group("value") or match.group("wrapped")
        value = int(value_text) if value_text.isdigit() else roman_to_int(value_text)
        if value is None or value <= 0:
            return None
        namespace = "arabic" if value_text.isdigit() else "roman"
        return value, namespace, candidate_template(text)
    if allow_letter_number:
        letter_match = _RE_LETTER_NUMBER.fullmatch(cleaned)
        if letter_match is not None and (value := int(letter_match.group("page"))) > 0:
            return value, letter_match.group("prefix").upper(), candidate_template(text)
    if len(cleaned.split()) <= 6:
        match_lead = _RE_LEADING_NUMBER.match(cleaned)
        if match_lead is not None and (val := int(match_lead.group("value"))) > 0:
            return val, "arabic", candidate_template(text)
        match_trail = _RE_TRAILING_NUMBER.match(cleaned)
        if match_trail is not None and (val := int(match_trail.group("value"))) > 0:
            return val, "arabic", candidate_template(text)
    return None


def _table_context(node: object) -> tuple[bool, bool]:
    current: object | None = node
    while current is not None:
        if str(getattr(current, "name", "")).casefold() == "table":
            semantic = _semantic(current) or _actual_break(current)
            row = getattr(node, "find_parent", None)
            parent_row = row("tr") if callable(row) else None
            semantic = semantic or bool(
                parent_row is not None and _semantic(parent_row)
            )
            return True, semantic
        current = _parent(current)
    return False, False


def _node_path(node: object) -> tuple[int, ...]:
    path: list[int] = []
    current: object | None = node
    while current is not None:
        parent = _parent(current)
        if parent is None:
            break
        contents = getattr(parent, "contents", ())
        try:
            path.append(contents.index(current))
        except (AttributeError, ValueError):
            return ()
        current = parent
    return tuple(reversed(path))


def _resolve_path(root: object, path: tuple[int, ...]) -> object | None:
    current: object | None = root
    for index in path:
        contents = getattr(current, "contents", ()) if current is not None else ()
        if index < 0 or index >= len(contents):
            return None
        current = contents[index]
    return current


def _hr_candidate_nodes(
    soup: object, *, allow_letter_number: bool = True
) -> list[dict[str, Any]]:
    finder = getattr(soup, "find_all", None)
    if not callable(finder):
        return []
    hrs = finder("hr")
    if len(hrs) < 3:
        return []
    candidates: list[dict[str, Any]] = []
    seen: set[int] = set()
    for hr in hrs:
        for method_name in ("find_previous_sibling", "find_next_sibling"):
            step = 0
            curr = getattr(hr, method_name, lambda: None)()
            while curr is not None and step < 2:
                node_id = id(curr)
                if node_id not in seen and not _hidden(curr) and not _toc_node(curr):
                    text = _node_text(curr)
                    if text and len(text) <= 80:
                        parsed = _parse_value(
                            text, allow_letter_number=allow_letter_number
                        )
                        if parsed is not None:
                            seen.add(node_id)
                            in_table, _ = _table_context(curr)
                            value, namespace, template = parsed
                            candidates.append(
                                {
                                    "node": curr,
                                    "value": value,
                                    "namespace": namespace,
                                    "template": template,
                                    "text": text,
                                    "explicit": _semantic(curr),
                                    "actual_break": True,
                                    "table_footer": in_table,
                                    "path": _node_path(curr),
                                }
                            )
                            break
                curr = getattr(curr, method_name, lambda: None)()
                step += 1
    return candidates


def _candidate_nodes(
    soup: object, *, allow_letter_number: bool = True
) -> list[dict[str, Any]]:
    hr_candidates = _hr_candidate_nodes(soup, allow_letter_number=allow_letter_number)
    if len(hr_candidates) >= 3:
        return hr_candidates
    finder = getattr(soup, "find_all", None)
    if not callable(finder):
        return []
    candidates: list[dict[str, Any]] = []
    for node in finder(["font", "p", "div", "span", "td", "th", "b", "i", "a", "em"]):
        if _hidden(node) or _toc_node(node):
            continue
        text = _node_text(node)
        if not text or len(text) > 80:
            continue
        parsed = _parse_value(text, allow_letter_number=allow_letter_number)
        if parsed is None:
            continue
        parent = _parent(node)
        parent_name = str(getattr(parent, "name", "")).casefold()
        if (
            parent is not None
            and parent_name not in {"table", "tbody", "thead", "tfoot", "tr"}
            and _parse_value(
                _node_text(parent), allow_letter_number=allow_letter_number
            )
            == parsed
        ):
            continue
        in_table, table_semantic = _table_context(node)
        explicit = _semantic(node)
        actual_break = _actual_break(node)
        tag_name = str(getattr(node, "name", "")).casefold()
        if (
            in_table
            and not (table_semantic or explicit or actual_break)
            and (
                is_numeric_cell(text)
                or (parsed[1] == "arabic" and not re.search(r"(?i)\bpage\b", text))
            )
        ):
            continue
        if (
            not explicit
            and not actual_break
            and tag_name not in {"div", "span", "p", "td", "th", "font"}
        ):
            continue
        value, namespace, template = parsed
        candidates.append(
            {
                "node": node,
                "value": value,
                "namespace": namespace,
                "template": template,
                "text": text,
                "explicit": explicit,
                "actual_break": actual_break,
                "table_footer": in_table,
                "path": _node_path(node),
            }
        )
    return candidates


def enrich_html_analysis(
    analysis: PageMarkerAnalysis | None,
    soup: object,
    *,
    allow_letter_number: bool = True,
    source_text: str,
) -> PageMarkerAnalysis:
    """Add validated visible DOM markers to an existing analysis."""

    base = analysis or PageMarkerAnalysis(
        (), (), (), representation="html", source_text=source_text
    )
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for item in _candidate_nodes(soup, allow_letter_number=allow_letter_number):
        tag = str(getattr(item["node"], "name", "")).casefold()
        key = (tag, item["namespace"], item["template"], _attr_text(item["node"]))
        groups.setdefault(key, []).append(item)

    markers: list[PageMarker] = []
    decisions: list[PageMarkerDecision] = []
    runs: list[PageNumberRun] = []
    templates: list[TemplateEvidence] = []
    unresolved = list(base.unresolved)
    for members in groups.values():
        ordered = sorted(members, key=lambda item: item["path"])
        values = [item["value"] for item in ordered]
        valid = len(ordered) >= 3 and monotone_fraction(values, max_delta=3) >= 0.8
        break_members = [item for item in ordered if item["actual_break"]]
        explicit_single = len(break_members) == 1
        if explicit_single and not valid:
            ordered = break_members
        if not valid and not explicit_single:
            unresolved.extend(f"dom:{item['text']}" for item in ordered[:32])
            continue
        family = (
            PageMarkerKind.TABLE_FOOTER
            if any(item["table_footer"] for item in ordered)
            else PageMarkerKind.HTML_NODE
        )
        page_candidates = tuple(
            PageCandidate(
                0,
                0,
                -1,
                -1,
                item["text"],
                family,
                item["namespace"],
                item["value"],
                template=item["template"],
                exclusion="",
                coordinate_frame="dom",
                node_path=item["path"],
            )
            for item in ordered
        )
        if valid:
            run = PageNumberRun(
                family,
                ordered[0]["namespace"],
                page_candidates,
                monotone_fraction(values, max_delta=3),
                0.0,
                0.0,
                1.0,
                -1,
                -1,
                "html_dom",
            )
            runs.append(run)
        templates.append(
            TemplateEvidence(
                "html", 0, ordered[0]["template"], len(ordered), 1.0, family, ()
            )
        )
        for item in ordered:
            evidence = ("visible_dom_node", "repeated_page_structure")
            if item["explicit"]:
                evidence += ("explicit_page_semantics",)
            if item["actual_break"]:
                evidence += ("actual_page_break",)
            marker = PageMarker(
                0,
                0,
                item["text"],
                family,
                item["value"],
                representation="html",
                confidence=0.9 if item["explicit"] else 0.82,
                namespace=item["namespace"],
                family=family,
                evidence=evidence,
                coordinate_frame="dom",
                node_path=item["path"],
            )
            markers.append(marker)
            decisions.append(
                PageMarkerDecision(
                    marker,
                    PageMarkerAction.REMOVE,
                    "validated_visible_html_page_marker",
                    marker.confidence,
                    evidence,
                )
            )

    runs = unify_alternating_runs(runs)
    combined_markers = list(base.markers)
    combined_decisions = list(base.decisions)
    existing_paths = {
        marker.node_path for marker in combined_markers if marker.node_path
    }
    for marker, decision in zip(markers, decisions):
        if marker.node_path not in existing_paths:
            combined_markers.append(marker)
            combined_decisions.append(decision)
    key_fn = lambda m: (m.start_line or -1, m.start, m.node_path)
    combined_markers.sort(key=key_fn)
    combined_decisions.sort(key=lambda d: key_fn(d.marker))
    has_visible = any(marker.page_number is not None for marker in combined_markers)
    return replace(
        base,
        markers=tuple(combined_markers),
        decisions=tuple(combined_decisions),
        representation="html",
        source_text=source_text,
        page_number_runs=base.page_number_runs + tuple(runs),
        header_footer_templates=base.header_footer_templates + tuple(templates),
        unresolved=tuple(unresolved[:256]),
        terminal_state=PageMarkerTerminalState.NONE
        if has_visible
        else PageMarkerTerminalState.NO_VISIBLE_LABELS,
        coordinate_frame="html",
    )


def apply_html_page_decisions(soup: object, analysis: PageMarkerAnalysis) -> int:
    """Remove validated DOM markers using node paths, never source offsets."""
    removed = 0
    paths = {
        d.marker.node_path
        for d in analysis.decisions
        if d.action in {PageMarkerAction.REMOVE, PageMarkerAction.NORMALIZE}
        and d.marker.coordinate_frame == "dom"
        and d.marker.node_path
    }
    for path in sorted(paths, key=len, reverse=True):
        if (node := _resolve_path(soup, path)) is not None and callable(
            decompose := getattr(node, "decompose", None)
        ):
            decompose()
            removed += 1
    return removed


def refresh_html_analysis(
    analysis: PageMarkerAnalysis,
    text: str,
) -> PageMarkerAnalysis:
    """Rebuild text-frame evidence after DOM or table serialization."""

    from .ascii import analyze_page_markers

    fresh = analyze_page_markers(text, representation="html")
    dom_markers = tuple(
        marker for marker in analysis.markers if marker.coordinate_frame == "dom"
    )
    dom_decisions = tuple(
        decision
        for decision in analysis.decisions
        if decision.marker.coordinate_frame == "dom"
    )
    dom_runs = tuple(
        run for run in analysis.page_number_runs if run.strategy == "html_dom"
    )
    dom_templates = tuple(
        template
        for template in analysis.header_footer_templates
        if template.side == "html"
    )
    markers = list(fresh.markers)
    decisions = list(fresh.decisions)
    paths = {marker.node_path for marker in markers if marker.node_path}
    for marker, decision in zip(dom_markers, dom_decisions):
        if marker.node_path not in paths:
            markers.append(marker)
            decisions.append(decision)
    markers.sort(
        key=lambda marker: (marker.start_line or -1, marker.start, marker.node_path)
    )
    decisions.sort(
        key=lambda item: (
            item.marker.start_line or -1,
            item.marker.start,
            item.marker.node_path,
        )
    )
    has_visible = any(marker.page_number is not None for marker in markers)
    return replace(
        fresh,
        markers=tuple(markers),
        decisions=tuple(decisions),
        page_number_runs=fresh.page_number_runs + dom_runs,
        header_footer_templates=(fresh.header_footer_templates + dom_templates),
        unresolved=tuple((fresh.unresolved + analysis.unresolved)[:256]),
        terminal_state=(
            PageMarkerTerminalState.NONE
            if has_visible
            else PageMarkerTerminalState.NO_VISIBLE_LABELS
        ),
        coordinate_frame="html",
    )


__all__ = [
    "apply_html_page_decisions",
    "enrich_html_analysis",
    "extract_ascii_pre",
    "refresh_html_analysis",
]
