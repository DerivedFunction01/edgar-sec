"""Visible HTML page-marker analysis using DOM coordinates."""

from __future__ import annotations

import re
from dataclasses import replace
from itertools import pairwise
from typing import Any

from defs.regex import build_alternation
from defs.tables.numeric_cells import CURRENCY_TOKEN_RE, is_financial_placeholder
from defs.tables.tokens import is_numeric_cell
from defs.text.dates import contains_date

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
    PROSE_GUARD_STOP_WORDS,
)
from .layout import candidate_template
from .models import (
    InferredBoundary,
    PageCandidate,
    PageMarker,
    PageMarkerAction,
    PageMarkerAnalysis,
    PageMarkerDecision,
    PageMarkerKind,
    PageMarkerTerminalState,
    PageNumberRun,
    PageRegionReport,
    TemplateEvidence,
)
from .pre import extract_ascii_pre
from .prose import prose_stop_words
from .sequence import monotone_fraction, unify_alternating_runs

# Prose guard for lookalike footer tables (footnotes, comparison tables).
# Distinct page-guard stop-word hits in the flattened table text at or above
# this count mark the table as prose-bearing rather than page furniture.
_FOOTER_PROSE_STOP_MIN = 2
_FOOTER_MAX_CELLS = 8
_FOOTER_CELL_TEXT_LIMIT = 200

_LABEL_TAGS = ("font", "p", "div", "span", "td", "th", "b", "i", "a", "em")
_LABEL_TAG_PATTERN = build_alternation(_LABEL_TAGS)
_RAW_LABEL_RE = re.compile(
    rf"(?is)<(?P<tag>{_LABEL_TAG_PATTERN})\b[^>]*>"
    r"\s*(?:page\s+)?(?:[a-z]\s*[-\u2013\u2014]\s*)?"
    r"(?:\d{1,4}|[ivxlcdm]{1,8})\s*</(?P=tag)\s*>"
)
# Strong raw evidence: letter-number labels ("F-3"), explicit "page N" text,
# page-semantic class/id/name attributes, or page-break styles. Bare digit
# tokens are deliberately NOT strong: financial tables are full of them, so
# they must not justify a broad DOM candidate scan on their own.
_RAW_STRONG_TOKEN_RE = re.compile(
    r"(?is)(?:^|[>\s])(?:"
    r"[a-z]\s*[-\u2013\u2014]\s*\d{1,4}"
    r"|(?:page\s*)\d{1,4}"
    r")(?:\s*(?:<|$))"
)
_RAW_PAGE_ATTR_RE = re.compile(r"(?is)\b(?:class|id|name)\s*=\s*[\"'][^\"']*\bpage")
_MULTIYEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_THOUSANDS_RE = re.compile(r"\d{1,3}(?:,\d{3})+")
_DECIMAL_RE = re.compile(r"\d\.\d")
_PAREN_NUMBER_RE = re.compile(r"\(\s*[\d.,]+\s*\)")


def _raw_label_tags(source_text: str) -> tuple[str, ...] | None:
    """Return likely strong-label tags, or ``None`` when a broad scan is required.

    ``()`` means no strong raw label evidence exists. This is deliberately only
    a performance hint. DOM parsing and all existing visibility/table/sequence
    validation remain authoritative.
    """
    if not _RAW_STRONG_TOKEN_RE.search(source_text):
        if _has_page_structural_hint(source_text):
            return None
        return ()
    if _has_page_structural_hint(source_text):
        return None
    matched = {
        match.group("tag").casefold()
        for match in _RAW_LABEL_RE.finditer(source_text)
        if _RAW_STRONG_TOKEN_RE.search(match.group(0))
    }
    tags = tuple(tag for tag in _LABEL_TAGS if tag in matched)
    return tags or None


def html_has_page_label_evidence(source_text: str) -> bool:
    """Cheap raw-HTML probe for whether page-marker work is worthwhile.

    Callers may use this before ``parse_html`` to skip both parsing and DOM
    enrichment for documents with no strong labels, no horizontal rules, and
    no tables. It is a conservative gate: ``False`` means "no known page-label
    carrier exists", never "page numbers are absent".
    """
    if not source_text:
        return False
    lowered = source_text.casefold()
    return bool(
        _RAW_STRONG_TOKEN_RE.search(source_text)
        or "<hr" in lowered
        or "<table" in lowered
    )


def _has_page_structural_hint(source_text: str) -> bool:
    """Return whether raw HTML carries page-semantic attributes or breaks."""
    return bool(
        _RAW_PAGE_ATTR_RE.search(source_text) or "page-break" in source_text.casefold()
    )


def _footer_table_disqualifier(flat: str) -> str | None:
    """Return a rejection reason when table text looks financial, not footer."""
    if contains_date(flat):
        return "date"
    if len({year for year in _MULTIYEAR_RE.findall(flat)}) >= 2:
        return "multiyear"
    if CURRENCY_TOKEN_RE.search(flat):
        return "currency"
    if "%" in flat or _DECIMAL_RE.search(flat) or _THOUSANDS_RE.search(flat):
        return "financial_number"
    if _PAREN_NUMBER_RE.search(flat):
        return "parenthesized_number"
    distinct_stops = prose_stop_words(flat) & PROSE_GUARD_STOP_WORDS
    if len(distinct_stops) >= _FOOTER_PROSE_STOP_MIN:
        return "prose_stop_words"
    return None


def _table_footer_candidates(
    soup: object,
    *,
    allow_letter_number: bool = True,
    facts: _NodeFacts | None = None,
) -> list[dict[str, Any]]:
    """Emit page-number candidates from repeated one-row footer-table families.

    A family is a set of tables sharing shape (cell count, numeric-cell
    position, table/cell attribute text) with exactly one page-label cell and
    non-prose, non-financial remaining text. Promotion requires >= 3 members
    whose values are monotone. Guards discard lookalike tables before any
    sequence work: financial tokens (currency, percent, decimals, dates,
    multiyear, thousands separators), page-guard prose stop words derived
    empirically from ASCII footer/header corpora, oversized cells, and
    oversized cell counts. All downstream grouping and monotonicity validation
    in :func:`enrich_html_analysis` still applies.
    """
    finder = getattr(soup, "find_all", None)
    if not callable(finder):
        return []
    facts = facts or _NodeFacts()
    families: dict[tuple, list[tuple[int, dict[str, Any]]]] = {}
    for table in finder("table"):
        rows = table.find_all("tr")
        if len(rows) != 1:
            continue
        cells = rows[0].find_all(["td", "th"])
        if not 2 <= len(cells) <= _FOOTER_MAX_CELLS:
            continue
        texts = [facts.node_text(cell) for cell in cells]
        if any(len(text) > _FOOTER_CELL_TEXT_LIMIT for index, text in enumerate(texts)):
            continue
        parsed_cells = [
            _parse_value(text, allow_letter_number=allow_letter_number)
            if text and len(text) <= 8
            else None
            for text in texts
        ]
        label_positions = [
            index
            for index, parsed in enumerate(parsed_cells)
            if parsed is not None
            and (
                texts[index].isdigit()
                or _RE_LETTER_NUMBER.fullmatch(texts[index]) is not None
            )
        ]
        if len(label_positions) != 1:
            continue
        position = label_positions[0]
        flat = " | ".join(text for text in texts if text)
        if _footer_table_disqualifier(flat):
            continue
        if any(
            is_financial_placeholder(text) or is_numeric_cell(text)
            for index, text in enumerate(texts)
            if index != position
        ):
            continue
        value, namespace, template = parsed_cells[position]
        signature = (
            len(cells),
            position,
            facts.attr_text(table),
            facts.attr_text(cells[position]),
            namespace,
            template,
        )
        families.setdefault(signature, []).append(
            (
                _node_path(cells[position]),
                value,
                namespace,
                template,
                cells[position],
                texts[position],
                flat,
            )
        )
    candidates: list[dict[str, Any]] = []
    for members in families.values():
        if len(members) < 3:
            continue
        ordered = sorted(members, key=lambda item: item[0])
        # Multiyear comparison families carry several distinct years across
        # their label rows; a page footer names at most one reporting year.
        family_years = {
            year for member in ordered for year in _MULTIYEAR_RE.findall(member[6])
        }
        if len(family_years) >= 2:
            continue
        # Repeated namespaces (exhibit sections, TOC indices) restart page
        # values. Split the family at every value decrease and validate each
        # section independently instead of mixing them into one run.
        sections: list[list[tuple[int, int, str, str, object, str, str]]] = []
        for member in ordered:
            if sections and member[1] > sections[-1][-1][1]:
                sections[-1].append(member)
            else:
                sections.append([member])
        for section in sections:
            if len(section) < 3:
                continue
            values = [item[1] for item in section]
            if monotone_fraction(values, max_delta=3) < 0.8:
                continue
            for path, value, namespace, template, node, text, _flat in section:
                candidates.append(
                    {
                        "node": node,
                        "value": value,
                        "namespace": namespace,
                        "template": template,
                        "text": text,
                        "explicit": False,
                        "actual_break": False,
                        "table_footer": True,
                        "path": path,
                    }
                )
    return candidates


def _attrs(node: object) -> dict[str, Any]:
    value = getattr(node, "attrs", {})
    return value if isinstance(value, dict) else {}


class _NodeFacts:
    """Per-enrichment memo shared by every discovery strategy.

    Ancestor checks (hidden, TOC, page-break) and attribute/text extraction
    previously re-ran for every strategy over the same nodes. Facts are keyed
    by stable node identity and computed once per enrichment call.
    """

    def __init__(self) -> None:
        self._attr_text_cache: dict[int, str] = {}
        self._node_text_cache: dict[int, str] = {}
        self._hidden_cache: dict[int, bool] = {}
        self._toc_cache: dict[int, bool] = {}
        self._break_cache: dict[int, bool] = {}
        self._semantic_cache: dict[int, bool] = {}

    def attr_text(self, node: object) -> str:
        node_id = _stable_id(node)
        cached = self._attr_text_cache.get(node_id)
        if cached is None:
            cached = self._attr_text_cache[node_id] = _attr_text(node)
        return cached

    def node_text(self, node: object) -> str:
        node_id = _stable_id(node)
        cached = self._node_text_cache.get(node_id)
        if cached is None:
            cached = self._node_text_cache[node_id] = _node_text(node)
        return cached

    def hidden(self, node: object) -> bool:
        chain: list[object] = []
        current: object | None = node
        result = False
        while current is not None:
            cached = self._hidden_cache.get(_stable_id(current))
            if cached is not None:
                result = cached
                break
            chain.append(current)
            current = _parent(current)
        for element in reversed(chain):
            result = self._hidden_cache[_stable_id(element)] = (
                _hidden_self(element) or result
            )
        return self._hidden_cache[_stable_id(node)]

    def toc(self, node: object) -> bool:
        chain: list[object] = []
        current: object | None = node
        result = False
        while current is not None:
            cached = self._toc_cache.get(_stable_id(current))
            if cached is not None:
                result = cached
                break
            chain.append(current)
            current = _parent(current)
        for element in reversed(chain):
            result = self._toc_cache[_stable_id(element)] = _toc_self(element) or result
        return self._toc_cache[_stable_id(node)]

    def actual_break(self, node: object) -> bool:
        chain: list[object] = []
        current: object | None = node
        result = False
        while current is not None:
            cached = self._break_cache.get(_stable_id(current))
            if cached is not None:
                result = cached
                break
            chain.append(current)
            current = _parent(current)
        for element in reversed(chain):
            result = self._break_cache[_stable_id(element)] = (
                _break_self(element) or result
            )
        return self._break_cache[_stable_id(node)]

    def semantic(self, node: object) -> bool:
        node_id = _stable_id(node)
        cached = self._semantic_cache.get(node_id)
        if cached is None:
            cached = self._semantic_cache[node_id] = bool(
                _RE_PAGE_SEMANTIC.search(self.attr_text(node))
            )
        return cached


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


def _hidden_self(node: object) -> bool:
    attrs = _attrs(node)
    if "hidden" in attrs or str(attrs.get("aria-hidden", "")).casefold() == "true":
        return True
    return bool(
        _HIDDEN_STYLE_RE.search(str(attrs.get("style", "")))
        or _RE_HIDDEN_TEMPLATE.search(_attr_text(node))
    )


def _toc_self(node: object) -> bool:
    return bool(_RE_TOC_SEMANTIC.search(_attr_text(node)))


def _break_self(node: object) -> bool:
    style = str(_attrs(node).get("style", ""))
    return bool(_PAGE_BREAK_RE.search(style) and not _PAGE_BREAK_AVOID_RE.search(style))


def _hidden(node: object) -> bool:
    current: object | None = node
    while current is not None:
        if _hidden_self(current):
            return True
        current = _parent(current)
    return False


def _semantic(node: object) -> bool:
    return bool(_RE_PAGE_SEMANTIC.search(_attr_text(node)))


def _toc_node(node: object) -> bool:
    current: object | None = node
    while current is not None:
        if _toc_self(current):
            return True
        current = _parent(current)
    return False


def _actual_break(node: object) -> bool:
    current: object | None = node
    while current is not None:
        if _break_self(current):
            return True
        current = _parent(current)
    return False


# Containers whose only role is wrapping: their subtree labels belong to
# child nodes, which are scanned in their own right. Skipping deep text
# extraction on occupied element containers avoids re-walking the same
# subtree once per wrapper. Label-carrier tags (p, td, th, font, b, i, a,
# em) keep deep extraction.
_CONTAINER_SKIP_TAGS = frozenset(
    {"div", "span", "section", "table", "tbody", "thead", "tfoot", "tr", "center"}
)


def _has_element_child(node: object) -> bool:
    inner = getattr(node, "_node", node)
    child = getattr(inner, "child", None)
    if child is not None:
        while child is not None:
            tag = getattr(child, "tag", None)
            if isinstance(tag, str) and tag not in {"-text", "-comment"}:
                return True
            child = getattr(child, "next", None)
        return False
    find = getattr(node, "find", None)
    if callable(find):
        try:
            return find(True, recursive=False) is not None
        except TypeError:
            return False
    return False


def _sibling_signature(node: object, facts: _NodeFacts) -> str | None:
    """Describe the label node by its row siblings, or None when not in a row.

    In page footers the sibling cells repeat identical furniture (form title,
    company name) on every page. In a table of contents each number is paired
    with a unique prose title, which makes sibling signatures distinct.
    """
    parent = _parent(node)
    parent_name = str(getattr(parent, "name", "")).casefold()
    if parent_name != "tr":
        return None
    inner_parent = getattr(parent, "_node", parent)
    parts: list[str] = []
    inner_node = getattr(node, "_node", node)
    node_id = getattr(inner_node, "mem_id", None)
    child = getattr(inner_parent, "child", None)
    if child is not None:
        while child is not None:
            tag = getattr(child, "tag", None)
            if isinstance(tag, str) and tag not in {"-text", "-comment"}:
                child_id = getattr(child, "mem_id", None)
                if node_id is not None and child_id == node_id:
                    parts.append("#")
                else:
                    getter = getattr(child, "text", None)
                    try:
                        text = (
                            str(getter(deep=False, separator=" ", strip=True))
                            if callable(getter)
                            else ""
                        )
                    except TypeError:
                        text = str(getter()) if callable(getter) else ""
                    parts.append(f"{tag}:{text[:48]}")
            child = getattr(child, "next", None)
        return "|".join(parts)
    contents = getattr(parent, "contents", ())
    for element in contents:
        name = str(getattr(element, "name", "")).casefold()
        if not name:
            continue
        if element is node:
            parts.append("#")
        else:
            parts.append(f"{name}:{facts.node_text(element)[:48]}")
    return "|".join(parts)


def _group_is_toc_like(ordered: list[dict[str, Any]], facts: _NodeFacts) -> bool:
    """Return whether a validated section behaves like a table of contents.

    Requires several members with row siblings and a strong majority of
    distinct sibling signatures. Short exhibit TOCs qualify; page-footer
    families with identical furniture never do.
    """
    signatures = [
        signature
        for item in ordered
        if (signature := _sibling_signature(item["node"], facts)) is not None
    ]
    if len(signatures) < 4:
        return False
    return len(set(signatures)) / len(signatures) > 0.6


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


def _index_among_siblings(parent: object, node: object) -> int | None:
    """Locate ``node`` in ``parent``'s child ordering without structural equality.

    ``FastHtmlNode.contents`` exposes the parent's subtree in document order,
    so ``list.index`` performs subtree-wide structural comparisons that become
    quadratic on large tables. Underlying-node identity is exact and cheap.
    The iteration used here matches ``contents`` ordering, keeping paths
    consistent with :func:`_resolve_path`.
    """
    inner_parent = getattr(parent, "_node", parent)
    inner_node = getattr(node, "_node", node)
    node_id = getattr(inner_node, "mem_id", None)
    iterator = getattr(inner_parent, "iter", None)
    if callable(iterator):
        try:
            for index, child in enumerate(iterator(include_text=True)):
                if child is inner_node or (
                    node_id is not None and getattr(child, "mem_id", None) == node_id
                ):
                    return index
        except TypeError:
            pass
    contents = getattr(parent, "contents", ())
    for index, child in enumerate(contents):
        if child is node:
            return index
    try:
        return contents.index(node)
    except (AttributeError, ValueError):
        return None


def _node_path(node: object) -> tuple[int, ...]:
    path: list[int] = []
    current: object | None = node
    while current is not None:
        parent = _parent(current)
        if parent is None:
            break
        index = _index_among_siblings(parent, current)
        if index is None:
            return ()
        path.append(index)
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


def _stable_id(node: object) -> int:
    inner = getattr(node, "_node", node)
    return getattr(inner, "mem_id", id(node))


def _hr_candidate_nodes(
    soup: object,
    *,
    allow_letter_number: bool = True,
    facts: _NodeFacts | None = None,
) -> list[dict[str, Any]]:
    facts = facts or _NodeFacts()
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
            meaningful_steps = 0
            curr = getattr(hr, method_name, lambda: None)()
            while curr is not None and meaningful_steps < 2:
                node_id = _stable_id(curr)
                text = facts.node_text(curr)
                if text:
                    meaningful_steps += 1
                if (
                    text
                    and len(text) <= 80
                    and node_id not in seen
                    and not facts.hidden(curr)
                    and not facts.toc(curr)
                ):
                    parsed = _parse_value(text, allow_letter_number=allow_letter_number)
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
                                "explicit": facts.semantic(curr),
                                "actual_break": True,
                                "table_footer": in_table,
                                "path": _node_path(curr),
                            }
                        )
                        break
                curr = getattr(curr, method_name, lambda: None)()
    return candidates


def _candidate_nodes(
    soup: object,
    *,
    allow_letter_number: bool = True,
    source_text: str = "",
    facts: _NodeFacts | None = None,
) -> list[dict[str, Any]]:
    facts = facts or _NodeFacts()
    hr_candidates = _hr_candidate_nodes(
        soup, allow_letter_number=allow_letter_number, facts=facts
    )
    table_candidates = _table_footer_candidates(
        soup, allow_letter_number=allow_letter_number, facts=facts
    )
    strong_tags = _raw_label_tags(source_text) if source_text else None
    seen = {_stable_id(item["node"]) for item in [*hr_candidates, *table_candidates]}
    # Generic scan gating: strong labels justify a targeted (or broad) scan.
    # Bare-digit documents with a verified footer-table family skip it; bare
    # digits alone never justify it. HR-adjacent evidence keeps the broad scan.
    if strong_tags == () and table_candidates:
        return [*hr_candidates, *table_candidates]
    if strong_tags == () and not hr_candidates:
        return [*hr_candidates, *table_candidates]
    finder = getattr(soup, "find_all", None)
    if not callable(finder):
        return [*hr_candidates, *table_candidates]
    candidates: list[dict[str, Any]] = []
    tags = strong_tags or _LABEL_TAGS
    for node in finder(tags):
        tag_name = str(getattr(node, "name", "")).casefold()
        if tag_name in _CONTAINER_SKIP_TAGS and _has_element_child(node):
            # Occupied container: label discovery continues via its children,
            # and the innermost node becomes the marker candidate.
            continue
        if facts.hidden(node) or facts.toc(node):
            continue
        text = facts.node_text(node)
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
            and parent_name not in _CONTAINER_SKIP_TAGS
            and _parse_value(
                facts.node_text(parent), allow_letter_number=allow_letter_number
            )
            == parsed
            and not (
                strong_tags
                and tag_name in strong_tags
                and len(parsed[1]) == 1
                and parsed[1].isalpha()
            )
        ):
            continue
        in_table, table_semantic = _table_context(node)
        explicit = facts.semantic(node)
        actual_break = facts.actual_break(node)
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
        node_id = _stable_id(node)
        if node_id in seen:
            continue
        seen.add(node_id)
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
    return [*hr_candidates, *table_candidates, *candidates]


# Complement-interval analysis: uncovered source regions and neighbor-predicted
# recovery of missing page labels. All outputs are metadata only; recovery
# requires two independent signals (sequence prediction + literal source hit
# with matching tag context) and never authorizes removal.
_RECOVERY_MAX_GAP = 64
_REGION_LETTER_RE = re.compile(r"(?i)(?:^|[>\s])[a-z]\s*[-\u2013\u2014]\s*\d{1,4}\b")
_REGION_PAGE_RE = re.compile(r"(?i)(?:^|[>\s])page\s*\d{1,4}\b")
_REGION_DIGIT_RE = re.compile(r"(?:^|[>\s])\d{1,4}(?=[\s<]|$)")
_RECOVERY_TAG_CONTEXT = ("p", "td", "div", "font", "span")


def _token_pattern(label: str) -> re.Pattern:
    escaped = re.escape(label)
    if label.isdigit():
        return re.compile(rf"(?:^|[>\s]){escaped}(?=[\s<]|$)")
    return re.compile(rf"{escaped}", re.IGNORECASE)


def _merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _family_extents(
    source_text: str, runs: list[PageNumberRun]
) -> list[tuple[int, int]]:
    """Anchor each family by its first and last member labels in the source.

    Only two literal searches per family. The first anchor may over-cover into
    front matter for generic labels; the region classification tolerates that
    because over-coverage only delays head-region detection, never removal.
    """
    extents: list[tuple[int, int]] = []
    for run in runs:
        candidates = sorted(run.candidates, key=lambda item: item.node_path)
        if len(candidates) < 2:
            continue
        first_match = _token_pattern(candidates[0].text).search(source_text)
        if first_match is None:
            continue
        last_offset = None
        for match in _token_pattern(candidates[-1].text).finditer(source_text):
            last_offset = match.start()
        if last_offset is not None and last_offset >= first_match.start():
            extents.append((first_match.start(), last_offset))
    return _merge_intervals(extents)


def _region_report(source_text: str, start: int, end: int) -> PageRegionReport:
    region = source_text[start:end]
    letters = len(_REGION_LETTER_RE.findall(region))
    pages = len(_REGION_PAGE_RE.findall(region))
    digits = len(_REGION_DIGIT_RE.findall(region))
    if letters + pages >= 3:
        status = "referential_labels"
    elif digits >= 3:
        status = "weak_numeric"
    else:
        status = "likely_pageless"
    return PageRegionReport(
        start_offset=start,
        end_offset=end,
        status=status,
        letter_tokens=letters,
        page_tokens=pages,
        digit_tokens=digits,
    )


def _region_reports(
    source_text: str, covered: list[tuple[int, int]]
) -> tuple[PageRegionReport, ...]:
    reports: list[PageRegionReport] = []
    cursor = 0
    for start, end in covered:
        if start > cursor:
            reports.append(_region_report(source_text, cursor, start))
        cursor = max(cursor, end)
    if cursor < len(source_text):
        reports.append(_region_report(source_text, cursor, len(source_text)))
    return tuple(reports)


def _recover_run_gaps(
    source_text: str, run: PageNumberRun
) -> tuple[InferredBoundary, ...]:
    """Infer missing page boundaries for value gaps between confirmed neighbors.

    Runs without value gaps cost nothing. For each gap, the expected label is
    substituted into the left neighbor's observed text and searched in the
    bounded source interval between the two anchors; a hit with matching tag
    context becomes a metadata-only inferred boundary.
    """
    candidates = sorted(run.candidates, key=lambda item: item.node_path)
    boundaries: list[InferredBoundary] = []
    pairs = list(pairwise(candidates))
    has_gap = any(
        1 <= right.value - left.value - 1 <= _RECOVERY_MAX_GAP for left, right in pairs
    )
    if not has_gap:
        return ()
    position = 0
    for left, right in pairs:
        missing = right.value - left.value - 1
        if not 1 <= missing <= _RECOVERY_MAX_GAP:
            continue
        left_match = _token_pattern(left.text).search(source_text, position)
        if left_match is None:
            continue
        right_match = _token_pattern(right.text).search(source_text, left_match.end())
        if right_match is None:
            continue
        position = right_match.end()
        interval = source_text[left_match.end() : right_match.start()]
        digits = re.search(r"\d{1,4}", left.text)
        if digits is None:
            continue
        for value in range(left.value + 1, right.value):
            expected = left.text.replace(digits.group(), str(value), 1)
            hit = _token_pattern(expected).search(interval)
            if hit is None:
                continue
            window = interval[max(0, hit.start() - 80) : hit.start()].lower()
            if not any(f"<{tag}" in window for tag in _RECOVERY_TAG_CONTEXT):
                continue
            boundaries.append(
                InferredBoundary(
                    line=float(left_match.end() + hit.start()),
                    page_number=value,
                    namespace=run.namespace,
                    reason="bounded_literal_recovery",
                )
            )
    return tuple(boundaries)


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
    facts = _NodeFacts()
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for item in _candidate_nodes(
        soup,
        allow_letter_number=allow_letter_number,
        source_text=source_text,
        facts=facts,
    ):
        tag = str(getattr(item["node"], "name", "")).casefold()
        key = (
            tag,
            item["namespace"],
            item["template"],
            facts.attr_text(item["node"]),
        )
        groups.setdefault(key, []).append(item)

    markers: list[PageMarker] = []
    decisions: list[PageMarkerDecision] = []
    runs: list[PageNumberRun] = []
    templates: list[TemplateEvidence] = []
    unresolved = list(base.unresolved)
    for members in groups.values():
        ordered_all = sorted(members, key=lambda item: item["path"])
        # Repeated namespaces (exhibit sections, TOC indices) restart values.
        # Split at every value decrease so each section is judged alone
        # instead of mixing unrelated sequences into one run.
        sections: list[list[dict[str, Any]]] = []
        for item in ordered_all:
            if sections and item["value"] > sections[-1][-1]["value"]:
                sections[-1].append(item)
            else:
                sections.append([item])
        for ordered in sections:
            values = [item["value"] for item in ordered]
            valid = len(ordered) >= 3 and monotone_fraction(values, max_delta=3) >= 0.8
            if valid and _group_is_toc_like(ordered, facts):
                # TOC rows pair each number with unique prose titles, while
                # genuine page footers repeat the same neighboring furniture.
                unresolved.extend(f"dom:{item['text']}" for item in ordered[:32])
                continue
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
    recovered_boundaries = tuple(
        boundary for run in runs for boundary in _recover_run_gaps(source_text, run)
    )
    covered = _family_extents(source_text, runs)
    regions = _region_reports(source_text, covered)
    return replace(
        base,
        markers=tuple(combined_markers),
        decisions=tuple(combined_decisions),
        representation="html",
        source_text=source_text,
        page_number_runs=base.page_number_runs + tuple(runs),
        header_footer_templates=base.header_footer_templates + tuple(templates),
        inferred_boundaries=base.inferred_boundaries + recovered_boundaries,
        regions=regions,
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
