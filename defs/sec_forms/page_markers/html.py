"""Visible HTML page-marker analysis using DOM coordinates."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import replace
from itertools import pairwise
from typing import Any

from defs.regex import build_alternation
from defs.tables.numeric_cells import CURRENCY_TOKEN_RE, is_financial_placeholder
from defs.tables.tokens import is_numeric_cell
from defs.text.dates import contains_date
from defs.text.html import FastHtmlNode

from .candidates import roman_to_int
from .constants import (
    _HIDDEN_STYLE_RE,
    _RE_HIDDEN_TEMPLATE,
    _RE_LEADING_NUMBER,
    _RE_LETTER_NUMBER,
    _RE_TOC_SEMANTIC,
    _RE_TRAILING_NUMBER,
    _VALUE_RE,
    PROSE_GUARD_STOP_WORDS,
    page_hint_roles_for_attrs,
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
                page_hint_roles_for_attrs(_attrs(node))
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
    return "break" in page_hint_roles_for_attrs(_attrs(node))


def _hidden(node: object) -> bool:
    current: object | None = node
    while current is not None:
        if _hidden_self(current):
            return True
        current = _parent(current)
    return False


def _semantic(node: object) -> bool:
    return bool(page_hint_roles_for_attrs(_attrs(node)))


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
_MAX_GENERIC_NODES = 24_000
_GENERIC_HEAD_FRACTION = 0.6
_MIDDLE_STRIDE_BUDGET = 8_000
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


def _recursive_page_nodes(soup: object, tags: tuple[str, ...]) -> list[object] | None:
    """Return bounded edge nodes for recursively nested ``<page>`` trees.

    Some legacy filings nest every later page inside the previous ``page``
    element. A global tag scan repeatedly extracts the text of all ancestors.
    Leaf-page prefix/suffix windows retain header/footer discovery while
    avoiding the recursive body walk. ``None`` means the topology is not
    confidently recursive and callers should use the normal scan.
    """
    finder = getattr(soup, "find_all", None)
    if not callable(finder):
        return None
    pages = finder("page")
    if len(pages) < 4:
        return None
    selected: list[object] = []
    seen: set[int] = set()
    pages_with_content = 0
    for page in pages:
        inner = getattr(page, "_node", page)
        child = getattr(inner, "child", None)
        page_nodes: list[object] = []
        while child is not None:
            tag = getattr(child, "tag", None)
            if isinstance(tag, str) and tag not in {"-text", "-comment", "page"}:
                page_nodes.extend(FastHtmlNode(child).find_all(list(tags)))
            child = getattr(child, "next", None)
        if page_nodes:
            pages_with_content += 1
            for node in [*page_nodes[:12], *page_nodes[-12:]]:
                node_id = _stable_id(node)
                if node_id not in seen:
                    seen.add(node_id)
                    selected.append(node)
    if pages_with_content < 3:
        return None
    return selected


def _flatten_recursive_pages(soup: object) -> bool:
    """Unwrap nested page wrappers that carry no presentation attributes.

    Legacy filings sometimes encode every later page as a child of the prior
    ``<page>`` element. That makes every ancestor text query revisit the whole
    remaining document. Page wrappers are structural-only in this format, so
    flatten them before discovery while retaining all content nodes.
    """
    finder = getattr(soup, "find_all", None)
    if not callable(finder):
        return False
    pages = finder("page")
    if len(pages) < 4:
        return False
    nested = any(
        str(getattr(_parent(page), "name", "")).casefold() == "page" for page in pages
    )
    if not nested:
        return False
    for page in reversed(pages):
        attrs = getattr(page, "attrs", {})
        if attrs:
            continue
        unwrap = getattr(page, "unwrap", None)
        if callable(unwrap):
            unwrap()
    return True


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


_HAS_LABEL_SHAPE_RE = re.compile(r"\d|^[ivxlcdm]+$", re.IGNORECASE)

# Real documents never have ~2000 physical pages, so an arabic value in the
# calendar-year range is a heading, column period, or prose lead-in ("2015
# compared to 2014"), not a page number. Reject it before any grouping so
# year lookalikes cannot validate as page-marker runs.
_YEAR_VALUE_MIN = 1900
_YEAR_VALUE_MAX = 2100


def _parse_value(
    text: str, *, allow_letter_number: bool = True
) -> tuple[int, str, str] | None:
    if len(text) > 80 and not any(char.isdigit() for char in text):
        # Long digit-free text cannot parse as a label; skip the expensive
        # normalization (roman candidates are short by definition).
        return None
    parts = text.split()
    if not parts:
        return None
    cleaned = " ".join(parts)
    word_count = len(parts)
    match = _VALUE_RE.fullmatch(cleaned)
    if match is not None:
        value_text = match.group("value") or match.group("wrapped")
        value = int(value_text) if value_text.isdigit() else roman_to_int(value_text)
        if value is None or value <= 0:
            return None
        namespace = "arabic" if value_text.isdigit() else "roman"
        if (
            namespace == "arabic"
            and _YEAR_VALUE_MIN <= value <= _YEAR_VALUE_MAX
        ):
            return None
        return value, namespace, candidate_template(text)
    if allow_letter_number:
        letter_match = _RE_LETTER_NUMBER.fullmatch(cleaned)
        if letter_match is not None and (value := int(letter_match.group("page"))) > 0:
            return value, letter_match.group("prefix").upper(), candidate_template(text)
    if word_count <= 6:
        match_lead = _RE_LEADING_NUMBER.match(cleaned)
        if (
            match_lead is not None
            and _YEAR_VALUE_MIN
            <= (val := int(match_lead.group("value")))
            <= _YEAR_VALUE_MAX
        ):
            return None
        if match_lead is not None and val > 0:
            return val, "arabic", candidate_template(text)
        match_trail = _RE_TRAILING_NUMBER.match(cleaned)
        if (
            match_trail is not None
            and _YEAR_VALUE_MIN
            <= (val := int(match_trail.group("value")))
            <= _YEAR_VALUE_MAX
        ):
            return None
        if match_trail is not None and val > 0:
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


_HINT_MIN_ROLE_NODES = 3


def _node_hint_roles(node: object) -> tuple[str, ...]:
    """Resolve page-hint roles from one node's attributes via the shared table."""

    return page_hint_roles_for_attrs(_attrs(node))


def _hint_nodes(
    soup: object,
    *,
    allow_letter_number: bool = True,
    facts: _NodeFacts,
) -> tuple[list[dict[str, Any]], bool]:
    """Emit candidates from nodes carrying page-hint classes/ids.

    Attribute values are normalized (lowercase, separators stripped, digit
    runs collapsed) and resolved against the shared hint-alias table. Roles:
    ``number`` nodes are direct label candidates; ``break`` nodes are break
    candidates with bounded neighbor label probes; ``header``/``footer`` nodes
    are furniture candidates. Returns [] when fewer than three hint nodes of
    any single role exist, leaving discovery to the existing paths.
    """
    finder = getattr(soup, "find_all", None)
    if not callable(finder):
        return [], False
    try:
        attr_nodes = finder(True, attrs={"class": True})
    except TypeError:
        attr_nodes = finder(True)
    role_counts: Counter[str] = Counter()
    role_nodes: dict[str, list[tuple[object, tuple[str, ...]]]] = {}
    for node in attr_nodes:
        roles = _node_hint_roles(node)
        if not roles:
            continue
        for role in roles:
            role_counts[role] += 1
            role_nodes.setdefault(role, []).append((node, roles))
    if not any(count >= _HINT_MIN_ROLE_NODES for count in role_counts.values()):
        return [], False
    # Only explicit number-role classes justify skipping the generic scan;
    # break/header/footer hints merge into the normal paths instead.
    fast_path = role_counts.get("number", 0) >= _HINT_MIN_ROLE_NODES
    candidates: list[dict[str, Any]] = []
    seen: set[int] = set()

    def emit(node: object, *, roles: tuple[str, ...], actual_break: bool) -> None:
        node_id = _stable_id(node)
        if node_id in seen:
            return
        if facts.hidden(node) or facts.toc(node):
            return
        text = facts.node_text(node)
        if not text or len(text) > 80:
            return
        parsed = _parse_value(text, allow_letter_number=allow_letter_number)
        if parsed is None:
            return
        value, namespace, template = parsed
        seen.add(node_id)
        in_table, _ = _table_context(node)
        candidates.append(
            {
                "node": node,
                "value": value,
                "namespace": namespace,
                "template": template,
                "text": text,
                "explicit": True,
                "actual_break": actual_break,
                "table_footer": in_table,
                "path": _node_path(node),
                "hint_roles": roles,
            }
        )

    for node, roles in role_nodes.get("number", []):
        emit(node, roles=roles, actual_break=False)
    for node, roles in role_nodes.get("break", []):
        if "number" in roles:
            emit(node, roles=roles, actual_break=True)
            continue
        # Break nodes are boundaries, not labels; probe adjacent label text.
        for method_name in ("find_previous_sibling", "find_next_sibling"):
            meaningful = 0
            curr = getattr(node, method_name, lambda: None)()
            while curr is not None and meaningful < 2:
                text = facts.node_text(curr)
                if text:
                    meaningful += 1
                if text and len(text) <= 80:
                    parsed = _parse_value(text, allow_letter_number=allow_letter_number)
                    if parsed is not None:
                        emit(curr, roles=roles, actual_break=True)
                curr = getattr(curr, method_name, lambda: None)()
    for role in ("header", "footer"):
        for node, roles in role_nodes.get(role, []):
            if any(other in roles for other in ("number", "break")):
                continue
            emit(node, roles=roles, actual_break=False)
    return candidates, fast_path


def _candidate_nodes(
    soup: object,
    *,
    allow_letter_number: bool = True,
    source_text: str = "",
    facts: _NodeFacts | None = None,
) -> list[dict[str, Any]]:
    facts = facts or _NodeFacts()
    recursive_nodes = _recursive_page_nodes(soup, _LABEL_TAGS)
    hint_candidates, hint_fast_path = _hint_nodes(
        soup, allow_letter_number=allow_letter_number, facts=facts
    )
    table_candidates = _table_footer_candidates(
        soup, allow_letter_number=allow_letter_number, facts=facts
    )
    # Hint fast path engages only on explicit number-role classes; break and
    # header/footer hints merge into the normal paths so documents with weak
    # hints never starve generic discovery.
    if hint_fast_path:
        return _dedupe_candidates([*hint_candidates, *table_candidates])
    hr_candidates = (
        []
        if recursive_nodes is not None
        else _hr_candidate_nodes(
            soup, allow_letter_number=allow_letter_number, facts=facts
        )
    )
    strong_tags = _raw_label_tags(source_text) if source_text else None
    seen = {
        _stable_id(item["node"])
        for item in [*hr_candidates, *table_candidates, *hint_candidates]
    }
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
    if recursive_nodes is not None:
        nodes = [
            node
            for node in recursive_nodes
            if str(getattr(node, "name", "")).casefold() in tags
        ]
    else:
        nodes = finder(tags)
    if len(nodes) > _MAX_GENERIC_NODES:
        head = int(_MAX_GENERIC_NODES * _GENERIC_HEAD_FRACTION)
        tail = _MAX_GENERIC_NODES - head
        # Large documents: probe front/back windows fully and stride-hop the
        # middle (footers repeat every few hundred nodes, so coarse sampling
        # retains them) instead of walking every node.
        middle = nodes[head:-tail]
        stride = max(1, len(middle) // _MIDDLE_STRIDE_BUDGET)
        nodes = [*nodes[:head], *middle[::stride], *nodes[-tail:]]
    for node in nodes:
        tag_name = str(getattr(node, "name", "")).casefold()
        if tag_name in _CONTAINER_SKIP_TAGS and _has_element_child(node):
            # Occupied container: label discovery continues via its children,
            # and the innermost node becomes the marker candidate.
            continue
        if facts.hidden(node) or facts.toc(node):
            continue
        # Most repeated page labels are leaf-like nodes whose text is directly
        # attached to the candidate element.  Avoid flattening the entire
        # subtree (often thousands of content nodes) before checking the label.
        # Nested labels still use the existing recursive extraction fallback.
        text = _raw_shallow_text(node)
        if not text:
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
                parent_text := facts.node_text(parent),
                allow_letter_number=allow_letter_number,
            )
            == parsed
            and len(parent_text) <= 240
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
    return _dedupe_candidates(
        [*hr_candidates, *table_candidates, *hint_candidates, *candidates]
    )


# Complement-interval analysis: uncovered source regions and neighbor-predicted
# recovery of missing page labels. All outputs are metadata only; recovery
# requires two independent signals (sequence prediction + literal source hit
# with matching tag context) and never authorizes removal.
_RECOVERY_MAX_GAP = 64
_RECOVERY_STRIDE_TARGET = 400
_RECOVERY_EXPANSION = 6
# Node-visit budget for the depth-bounded route DFS during gap recovery.
_RECOVERY_ROUTE_BUDGET = 256
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


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[int] = set()
    deduped: list[dict[str, Any]] = []
    for item in candidates:
        node_id = _stable_id(item["node"])
        if node_id in seen:
            continue
        seen.add(node_id)
        deduped.append(item)
    return deduped


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
    _flatten_recursive_pages(soup)
    facts = _NodeFacts()
    candidates = _candidate_nodes(
        soup,
        allow_letter_number=allow_letter_number,
        source_text=source_text,
        facts=facts,
    )
    markers, decisions, runs, templates, unresolved = _validate_candidate_groups(
        candidates, facts
    )
    unresolved = [*base.unresolved, *unresolved]
    runs = unify_alternating_runs(runs)
    return _finalize_html_analysis(
        base,
        source_text,
        facts,
        candidates,
        markers,
        decisions,
        runs,
        templates,
        unresolved,
    )


def _validate_candidate_groups(
    candidates: list[dict[str, Any]], facts: _NodeFacts
) -> tuple[
    list[PageMarker],
    list[PageMarkerDecision],
    list[PageNumberRun],
    list[TemplateEvidence],
    list[str],
]:
    """Group candidates, split value sections, and validate each independently."""
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for item in candidates:
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
    unresolved: list[str] = []
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
            values_monotone = monotone_fraction(values, max_delta=3) >= 0.8
            valid = len(ordered) >= 3 and values_monotone
            if (
                not valid
                and len(ordered) >= 2
                and values_monotone
                and all(item["actual_break"] for item in ordered)
            ):
                # Every member carries explicit page-break semantics; a short
                # monotone section of such nodes is still strong evidence.
                valid = True
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

    return markers, decisions, runs, templates, unresolved


def _ancestor_chain(node: object) -> list[object]:
    chain: list[object] = []
    current: object | None = node
    while current is not None:
        chain.append(current)
        current = _parent(current)
    return chain


def _raw_shallow_text(inner: object) -> str:
    getter = getattr(inner, "text", None)
    if not callable(getter):
        return ""
    try:
        return str(getter(deep=False, separator=" ", strip=True))
    except TypeError:
        try:
            return str(getter())
        except Exception:  # noqa: BLE001
            return ""


def _sibling_range(
    left_item: dict[str, Any], right_item: dict[str, Any]
) -> list[object] | None:
    """Return wrapper-level nodes strictly between the two confirmed nodes.

    Walks both ancestor chains to the lowest common ancestor and collects the
    LCA's children between the two chain branches (case 1: markers are direct
    siblings; case 2: the branches are repeated page containers).
    """
    lchain = _ancestor_chain(left_item["node"])
    rchain = _ancestor_chain(right_item["node"])
    rids = {_stable_id(item) for item in rchain}
    lca_depth = None
    for depth, ancestor in enumerate(lchain):
        if _stable_id(ancestor) in rids:
            lca_depth = depth
            break
    if lca_depth is None or lca_depth == 0:
        return None
    lca = lchain[lca_depth]
    rca_depth = next(
        depth
        for depth, ancestor in enumerate(rchain)
        if _stable_id(ancestor) == _stable_id(lca)
    )
    if lca_depth == 0 or rca_depth == 0:
        return None
    left_branch = lchain[lca_depth - 1]
    right_branch = rchain[rca_depth - 1]
    if _stable_id(left_branch) == _stable_id(right_branch):
        return None
    inner_lca = getattr(lca, "_node", lca)
    inner_left = getattr(left_branch, "_node", left_branch)
    inner_right = getattr(right_branch, "_node", right_branch)
    left_id = getattr(inner_left, "mem_id", None)
    right_id = getattr(inner_right, "mem_id", None)
    between: list[object] = []
    child = getattr(inner_lca, "child", None)
    if child is not None and left_id is not None and right_id is not None:
        active = False
        while child is not None:
            child_id = getattr(child, "mem_id", None)
            if child_id == left_id:
                active = True
            elif child_id == right_id:
                break
            elif active and getattr(child, "tag", None) not in (
                None,
                "-text",
                "-comment",
            ):
                between.append(FastHtmlNode(child))
            child = getattr(child, "next", None)
        return between
    contents = getattr(lca, "contents", ())
    active = False
    for element in contents:
        if element is left_branch:
            active = True
        elif element is right_branch:
            break
        elif active and getattr(element, "name", None):
            between.append(element)
    return between


def _adjacent_sibling_tag(inner: object, step: str) -> str:
    current = getattr(inner, step, None)
    while current is not None:
        tag = getattr(current, "tag", None) or getattr(current, "name", None)
        if isinstance(tag, str) and tag not in {"-text", "-comment"}:
            return tag.casefold()
        current = getattr(current, step, None)
    return ""


def _context_signature(node: object, facts: _NodeFacts) -> tuple:
    """Shape-based local signature: structure only, never text content.

    Body text differs on every page, so signature equality is computed from
    the parent tag, the node's own tag and normalized attributes, the
    adjacent sibling tags, and whether the node carries a digit. Nodes from
    a different generator context (headings, TOC cells) fail the comparison
    against confirmed footer/header anchors and stay inferred-only.
    """
    inner = getattr(node, "_node", node)
    parent = _parent(node)
    text = facts.node_text(node)
    return (
        str(getattr(parent, "name", "")).casefold() if parent is not None else "",
        str(getattr(node, "name", "")).casefold(),
        facts.attr_text(node),
        _adjacent_sibling_tag(inner, "prev"),
        _adjacent_sibling_tag(inner, "next"),
        bool(re.search(r"\d", text)),
    )


def _recover_between_nodes(
    left_item: dict[str, Any],
    right_item: dict[str, Any],
    run: PageNumberRun,
    facts: _NodeFacts,
    expected: set[int],
) -> list[dict[str, Any]]:
    """Locate missing label nodes between two confirmed anchors.

    Stride-samples the LCA sibling range; on any hit, expands to neighboring
    siblings. Nodes not matching the confirmed marker's route spine are
    skipped without deep text extraction. Recovered nodes are candidate
    dicts and still pass full group/section/TOC validation afterwards.
    """
    between = _sibling_range(left_item, right_item)
    if not between:
        return []
    # Route spine from the LCA branch down to the confirmed marker node.
    left_chain = _ancestor_chain(left_item["node"])
    right_ids = {_stable_id(item) for item in _ancestor_chain(right_item["node"])}
    lca_depth = next(
        (depth for depth, ancestor in enumerate(left_chain)
         if _stable_id(ancestor) in right_ids),
        None,
    )
    if lca_depth is None or lca_depth == 0:
        return []
    spine: list[str] = []
    current = left_item["node"]
    branch_id = _stable_id(left_chain[lca_depth - 1])
    while current is not None:
        current_id = _stable_id(current)
        spine.append(str(getattr(current, "name", "")).casefold())
        if current_id == branch_id:
            break
        current = _parent(current)
    spine.reverse()  # [branch, ..., marker]
    spine_tags = spine[1:]

    def try_emit(node: object, roles_check: bool = True) -> dict[str, Any] | None:
        if roles_check and (facts.hidden(node) or facts.toc(node)):
            return None
        # Shallow-first: leaf-like page labels keep their text directly on the
        # candidate element, so the cheap non-recursive extraction answers the
        # common case without flattening content subtrees. Deep extraction
        # only runs when no shallow text exists (nested-span labels).
        text = _raw_shallow_text(node)
        if not text:
            text = facts.node_text(node)
        if not text or len(text) > 80:
            return None
        parsed = _parse_value(text, allow_letter_number=True)
        if parsed is None or parsed[0] not in expected:
            return None
        value, namespace, template = parsed
        if namespace != run.namespace:
            return None
        # Signature gate: the recovered node must share the confirmed
        # anchors' structural context, otherwise it is a lookalike (heading,
        # TOC reference) and stays inferred-only rather than strippable.
        # Explicit page-break semantics bypass the gate: a label inside a
        # page-break container (e.g. div#PN with PAGE-BREAK-AFTER) carries
        # stronger evidence than structural context, including break roles
        # inherited from an ancestor.
        explicit_break = _actual_break(node)
        if not explicit_break and _context_signature(node, facts) not in anchor_signatures:
            return None
        in_table, _ = _table_context(node)
        return {
            "node": node,
            "value": value,
            "namespace": namespace,
            "template": template,
            "text": text,
            "explicit": False,
            "actual_break": explicit_break,
            "table_footer": in_table,
            "path": _node_path(node),
            "recovered": True,
        }

    recovered: list[dict[str, Any]] = []
    emitted_values: set[int] = set()
    anchor_signatures = {
        _context_signature(left_item["node"], facts),
        _context_signature(right_item["node"], facts),
    }
    stride = max(1, len(between) // _RECOVERY_STRIDE_TARGET)

    def route_descend(node: object) -> list[dict[str, Any]]:
        # Route-spine descent: depth-bounded DFS over children matching the
        # confirmed marker's ancestor tags, skipping content subtrees. Purely
        # tag-based until the terminal node, so foreign branches cost one
        # child walk and never any text extraction. Every matching branch is
        # tried (page containers repeat FTR/HDR wrappers around the label),
        # bounded by _RECOVERY_ROUTE_BUDGET node visits.
        hits: list[dict[str, Any]] = []
        stack: list[tuple[object, int]] = [(node, 0)]
        budget = _RECOVERY_ROUTE_BUDGET

        def route_priority(child: object) -> int:
            """Prioritize page-number branches within page-break wrappers."""
            roles = page_hint_roles_for_attrs(_attrs(child))
            token = " ".join(
                str(_attrs(child).get(key, "")).casefold()
                for key in ("id", "class", "name")
            )
            score = 0
            if "number" in roles:
                score += 40
            if any(alias in token for alias in ("pn", "pageno", "pagenum", "page-number")):
                score += 35
            if "break" in roles:
                score += 25
            if "footer" in roles or "header" in roles:
                score += 10
            return score

        while stack and (budget > 0 or stack[-1][1] == len(spine_tags)) and not expected.issubset(emitted_values):
            current, depth = stack.pop()
            inner = getattr(current, "_node", current)
            child = getattr(inner, "child", None)
            matching: list[object] = []
            if depth < len(spine_tags):
                expected_tag = spine_tags[depth]
                while child is not None:
                    tag = getattr(child, "tag", None)
                    if isinstance(tag, str) and tag.casefold() == expected_tag:
                        matching.append(child)
                    child = getattr(child, "next", None)
            if not matching:
                # Dead end: either the terminal depth or a wrapper level whose
                # subtree ends short of the anchor route (nested page-break
                # containers). The node's own text must carry the expected
                # value, so emit it through the full gate stack.
                budget -= 1
                hit = try_emit(current)
                if hit is not None:
                    hits.append(hit)
                continue
            # Stack order is reversed so the highest-priority branch is popped
            # first. This favors PN/page-number branches over FTR/HDR filler.
            matching.sort(key=route_priority)
            for child in matching:
                if depth + 1 < len(spine_tags):
                    if budget <= 0:
                        break
                    budget -= 1
                stack.append((FastHtmlNode(child), depth + 1))
        return hits

    def emit(hit: dict[str, Any] | None) -> None:
        if hit is not None and hit["value"] not in emitted_values:
            emitted_values.add(hit["value"])
            recovered.append(hit)

    def scan(index: int) -> None:
        node = between[index]
        if spine_tags and str(getattr(node, "name", "")).casefold() != spine_tags[0]:
            # Early route rejection: the sibling's own tag already diverges
            # from the confirmed marker route (e.g. a p where the anchors are
            # div -> div -> hr), so skip text parsing and try the route
            # descent directly; if the route fails too, the node is dropped.
            for hit in route_descend(node):
                emit(hit)
            return
        emit(try_emit(node))
        for hit in route_descend(node) if spine_tags else ():
            emit(hit)

    # Page labels cluster around visible breaks, so scan a bounded window
    # around each <hr> sibling before the general stride walk; the early
    # exit keeps this a pure shortcut when the windows find everything.
    hr_indices = [
        index
        for index, node in enumerate(between)
        if str(getattr(node, "name", "")).casefold() == "hr"
    ]
    if hr_indices:
        window = _RECOVERY_EXPANSION * 2
        seen_hr: set[int] = set()
        for hr_index in hr_indices:
            for index in range(max(0, hr_index - window), min(len(between), hr_index + window + 1)):
                if index in seen_hr or expected.issubset(emitted_values):
                    continue
                seen_hr.add(index)
                scan(index)
    for index in range(0, len(between), stride):
        if expected.issubset(emitted_values):
            break
        scan(index)
        if stride > 1:
            for offset in range(1, _RECOVERY_EXPANSION + 1):
                if expected.issubset(emitted_values):
                    break
                if index - offset >= 0:
                    scan(index - offset)
                if index + offset < len(between):
                    scan(index + offset)
    # Rule-element boundary recovery: when no label element exists for a
    # missing page but the gap's <hr> count equals the page span, each hr is
    # the literal boundary of exactly one page (label renders before its
    # trailing rule). The k-th hr then belongs to page left+1+k, so remaining
    # values map positionally onto real strippable boundary nodes.
    remaining = sorted(expected - emitted_values)
    if remaining and len(hr_indices) == right_item["value"] - left_item["value"]:
        for value in remaining:
            hr_position = value - left_item["value"] - 1
            if hr_position < 0 or hr_position >= len(hr_indices):
                continue
            node = between[hr_indices[hr_position]]
            recovered.append(
                {
                    "node": node,
                    "value": value,
                    "namespace": run.namespace,
                    "template": "hr",
                    "text": "",
                    "explicit": False,
                    "actual_break": True,
                    "table_footer": False,
                    "path": _node_path(node),
                    "recovered": True,
                }
            )
    return recovered


def _finalize_html_analysis(
    base: PageMarkerAnalysis,
    source_text: str,
    facts: _NodeFacts,
    candidates: list[dict[str, Any]],
    markers: list[PageMarker],
    decisions: list[PageMarkerDecision],
    runs: list[PageNumberRun],
    templates: list[TemplateEvidence],
    unresolved: list[str],
) -> PageMarkerAnalysis:
    # DOM gap recovery: for validated runs with missing page values, locate
    # the missing label nodes between the bracketing confirmed nodes (LCA
    # sibling walk + route-spine descent + stride sampling) and re-validate
    # the union so recovered nodes become real strippable markers.
    by_path = {item["path"]: item for item in candidates if item.get("path")}
    recovered: list[dict[str, Any]] = []
    for run in runs:
        ordered = sorted(run.candidates, key=lambda item: item.node_path)
        for left, right in pairwise(ordered):
            missing = right.value - left.value - 1
            if not 1 <= missing <= _RECOVERY_MAX_GAP:
                continue
            left_item = by_path.get(left.node_path)
            right_item = by_path.get(right.node_path)
            if left_item is None or right_item is None:
                continue
            expected = set(range(left.value + 1, right.value))
            recovered.extend(
                _recover_between_nodes(left_item, right_item, run, facts, expected)
            )
    if recovered:
        candidates = [*candidates, *recovered]
        markers, decisions, runs, templates, unresolved2 = _validate_candidate_groups(
            candidates, facts
        )
        unresolved = [*unresolved, *unresolved2]
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
    recovered_boundaries = []
    for run in runs:
        observed = {candidate.value for candidate in run.candidates}
        for boundary in _recover_run_gaps(source_text, run):
            if boundary.page_number not in observed:
                recovered_boundaries.append(boundary)
    recovered_boundaries = tuple(recovered_boundaries)
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


def apply_html_page_decisions(soup: object, analysis: PageMarkerAnalysis) -> list:
    """Remove validated DOM markers using node paths, never source offsets.

    Returns the removed nodes so callers can inspect what was stripped;
    empty list means nothing was removed.
    """
    removed_nodes: list = []
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
            removed_nodes.append(node)
    return removed_nodes


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
