"""Candidate discovery from HTML DOM."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from defs.tables.numeric_cells import CURRENCY_TOKEN_RE, is_financial_placeholder
from defs.tables.tokens import is_numeric_cell
from defs.text.dates import contains_date

from ..constants import (
    _RE_LETTER_NUMBER,
    PROSE_GUARD_STOP_WORDS,
    page_hint_roles_for_attrs,
)
from ..prose import prose_stop_words
from ..sequence import monotone_fraction
from .dom import (
    _CONTAINER_SKIP_TAGS,
    _GENERIC_HEAD_FRACTION,
    _MAX_GENERIC_NODES,
    _MIDDLE_STRIDE_BUDGET,
    _attrs,
    _has_element_child,
    _node_path,
    _NodeFacts,
    _parent,
    _raw_shallow_text,
    _recursive_page_nodes,
    _stable_id,
    _table_context,
)
from .parsing import _parse_value
from .probes import (
    _DECIMAL_RE,
    _MULTIYEAR_RE,
    _PAREN_NUMBER_RE,
    _THOUSANDS_RE,
    _raw_label_tags,
)

_FOOTER_PROSE_STOP_MIN = 2
_FOOTER_MAX_CELLS = 8
_FOOTER_CELL_TEXT_LIMIT = 200
_HINT_MIN_ROLE_NODES = 3


def _footer_table_disqualifier(flat: str) -> str | None:
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
        family_years = {
            year for member in ordered for year in _MULTIYEAR_RE.findall(member[6])
        }
        if len(family_years) >= 2:
            continue
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


def _node_hint_roles(node: object) -> tuple[str, ...]:
    return page_hint_roles_for_attrs(_attrs(node))


def _hint_nodes(
    soup: object,
    *,
    allow_letter_number: bool = True,
    facts: _NodeFacts,
) -> tuple[list[dict[str, Any]], bool]:
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
    recipe_profile: frozenset[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    facts = facts or _NodeFacts()
    recursive_nodes = _recursive_page_nodes(soup, ("font", "p", "div", "span", "td", "th", "b", "i", "a", "em"))
    recipe_tags = tuple(sorted({tag for tag, _ in recipe_profile or ()}))
    if recipe_profile:
        hint_candidates, hint_fast_path = [], False
        table_candidates = []
        hr_candidates = []
    else:
        hint_candidates, hint_fast_path = _hint_nodes(
            soup, allow_letter_number=allow_letter_number, facts=facts
        )
        table_candidates = _table_footer_candidates(
            soup, allow_letter_number=allow_letter_number, facts=facts
        )
    if hint_fast_path:
        result = _dedupe_candidates([*hint_candidates, *table_candidates])
        for item in result:
            item["attr_text"] = facts.attr_text(item["node"])
        return result
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
    if strong_tags == () and table_candidates:
        return [*hr_candidates, *table_candidates]
    if strong_tags == () and not hr_candidates:
        return [*hr_candidates, *table_candidates]
    finder = getattr(soup, "find_all", None)
    if not callable(finder):
        return [*hr_candidates, *table_candidates]
    candidates: list[dict[str, Any]] = []
    tags = recipe_tags or strong_tags or ("font", "p", "div", "span", "td", "th", "b", "i", "a", "em")
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
        middle = nodes[head:-tail]
        stride = max(1, len(middle) // _MIDDLE_STRIDE_BUDGET)
        nodes = [*nodes[:head], *middle[::stride], *nodes[-tail:]]
    for node in nodes:
        tag_name = str(getattr(node, "name", "")).casefold()
        if recipe_profile and (tag_name, facts.attr_text(node)) not in recipe_profile:
            continue
        if tag_name in _CONTAINER_SKIP_TAGS and _has_element_child(node):
            continue
        if facts.hidden(node) or facts.toc(node):
            continue
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
    result = _dedupe_candidates(
        [*hr_candidates, *table_candidates, *hint_candidates, *candidates]
    )
    for item in result:
        item["attr_text"] = facts.attr_text(item["node"])
    return result


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


__all__ = [
    "_CONTAINER_SKIP_TAGS",
    "_GENERIC_HEAD_FRACTION",
    "_MAX_GENERIC_NODES",
    "_MIDDLE_STRIDE_BUDGET",
    "_candidate_nodes",
    "_dedupe_candidates",
    "_footer_table_disqualifier",
    "_hint_nodes",
    "_hr_candidate_nodes",
    "_node_hint_roles",
    "_table_footer_candidates",
]
