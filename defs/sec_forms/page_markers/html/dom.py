"""DOM memoization, node identity, and ancestor-chain utilities."""

from __future__ import annotations

import re
from typing import Any

from defs.text.html import FastHtmlNode

from ..constants import page_hint_roles_for_attrs

_MAX_GENERIC_NODES = 24_000
_GENERIC_HEAD_FRACTION = 0.6
_MIDDLE_STRIDE_BUDGET = 8_000
_CONTAINER_SKIP_TAGS = frozenset(
    {"div", "span", "section", "table", "tbody", "thead", "tfoot", "tr", "center"}
)


def _attrs(node: object) -> dict[str, Any]:
    value = getattr(node, "attrs", {})
    return value if isinstance(value, dict) else {}


class _NodeFacts:
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
    from ..constants import _HIDDEN_STYLE_RE, _RE_HIDDEN_TEMPLATE
    return bool(
        _HIDDEN_STYLE_RE.search(str(attrs.get("style", "")))
        or _RE_HIDDEN_TEMPLATE.search(_attr_text(node))
    )


def _toc_self(node: object) -> bool:
    from ..constants import _RE_TOC_SEMANTIC
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


def _raw_shallow_text(inner: object) -> str:
    getter = getattr(inner, "text", None)
    if not callable(getter):
        return ""
    try:
        return str(getter(deep=False, separator=" ", strip=True))
    except TypeError:
        try:
            return str(getter())
        except (AttributeError, TypeError, ValueError):
            return ""


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
    from defs.text.html import FastHtmlNode
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


def _ancestor_chain(node: object) -> list[object]:
    chain: list[object] = []
    current: object | None = node
    while current is not None:
        chain.append(current)
        current = _parent(current)
    return chain


def _index_among_siblings(parent: object, node: object) -> int | None:
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


def _context_signature(node: object, facts: _NodeFacts) -> tuple:
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


def _sibling_range(
    left_item: dict[str, Any], right_item: dict[str, Any]
) -> list[object] | None:
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


__all__ = [
    "_NodeFacts",
    "_actual_break",
    "_adjacent_sibling_tag",
    "_ancestor_chain",
    "_attr_text",
    "_break_self",
    "_context_signature",
    "_flatten_recursive_pages",
    "_has_element_child",
    "_hidden",
    "_hidden_self",
    "_index_among_siblings",
    "_node_path",
    "_node_text",
    "_parent",
    "_raw_shallow_text",
    "_recursive_page_nodes",
    "_resolve_path",
    "_semantic",
    "_sibling_range",
    "_sibling_signature",
    "_stable_id",
    "_table_context",
    "_toc_node",
    "_toc_self",
]
