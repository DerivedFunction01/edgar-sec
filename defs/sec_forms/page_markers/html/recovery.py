"""DOM gap recovery and region classification for page-marker runs."""

from __future__ import annotations

import re
from itertools import pairwise
from typing import Any

from defs.text.html import FastHtmlNode

from ..constants import page_hint_roles_for_attrs
from ..models import InferredBoundary, PageNumberRun, PageRegionReport
from .dom import (
    _actual_break,
    _ancestor_chain,
    _attrs,
    _context_signature,
    _node_path,
    _NodeFacts,
    _parent,
    _raw_shallow_text,
    _sibling_range,
    _stable_id,
    _table_context,
)
from .parsing import _parse_value

_RECOVERY_MAX_GAP = 64
_RECOVERY_STRIDE_TARGET = 400
_RECOVERY_EXPANSION = 6
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


def _recover_between_nodes(
    left_item: dict[str, Any],
    right_item: dict[str, Any],
    run: PageNumberRun,
    facts: _NodeFacts,
    expected: set[int],
) -> list[dict[str, Any]]:
    between = _sibling_range(left_item, right_item)
    if not between:
        return []
    left_chain = _ancestor_chain(left_item["node"])
    right_ids = {_stable_id(item) for item in _ancestor_chain(right_item["node"])}
    lca_depth = next(
        (
            depth
            for depth, ancestor in enumerate(left_chain)
            if _stable_id(ancestor) in right_ids
        ),
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
    spine.reverse()
    spine_tags = spine[1:]

    def try_emit(node: object, roles_check: bool = True) -> dict[str, Any] | None:
        if roles_check and (facts.hidden(node) or facts.toc(node)):
            return None
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
        explicit_break = _actual_break(node)
        if (
            not explicit_break
            and _context_signature(node, facts) not in anchor_signatures
        ):
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
        hits: list[dict[str, Any]] = []
        stack: list[tuple[object, int]] = [(node, 0)]
        budget = _RECOVERY_ROUTE_BUDGET

        def route_priority(child: object) -> int:
            roles = page_hint_roles_for_attrs(_attrs(child))
            token = " ".join(
                str(_attrs(child).get(key, "")).casefold()
                for key in ("id", "class", "name")
            )
            score = 0
            if "number" in roles:
                score += 40
            if any(
                alias in token for alias in ("pn", "pageno", "pagenum", "page-number")
            ):
                score += 35
            if "break" in roles:
                score += 25
            if "footer" in roles or "header" in roles:
                score += 10
            return score

        while (
            stack
            and (budget > 0 or stack[-1][1] == len(spine_tags))
            and not expected.issubset(emitted_values)
        ):
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
                budget -= 1
                hit = try_emit(current)
                if hit is not None:
                    hits.append(hit)
                continue
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
            for hit in route_descend(node):
                emit(hit)
            return
        emit(try_emit(node))
        for hit in route_descend(node) if spine_tags else ():
            emit(hit)

    hr_indices = [
        index
        for index, node in enumerate(between)
        if str(getattr(node, "name", "")).casefold() == "hr"
    ]
    if hr_indices:
        window = _RECOVERY_EXPANSION * 2
        seen_hr: set[int] = set()
        for hr_index in hr_indices:
            for index in range(
                max(0, hr_index - window), min(len(between), hr_index + window + 1)
            ):
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


__all__ = [
    "_RECOVERY_EXPANSION",
    "_RECOVERY_MAX_GAP",
    "_RECOVERY_ROUTE_BUDGET",
    "_RECOVERY_STRIDE_TARGET",
    "_RECOVERY_TAG_CONTEXT",
    "_REGION_DIGIT_RE",
    "_REGION_LETTER_RE",
    "_REGION_PAGE_RE",
    "_family_extents",
    "_merge_intervals",
    "_recover_between_nodes",
    "_recover_run_gaps",
    "_region_reports",
    "_token_pattern",
]
