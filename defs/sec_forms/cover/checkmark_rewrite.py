"""Apply resolved cover checkbox decisions to text and table metadata."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import replace as dataclass_replace

from defs.sec_forms.cover.checkmark_candidates import _MARK_RE
from defs.sec_forms.cover.checkmark_models import (
    CheckboxCandidate,
    CoverCheckmarkResult,
)
from defs.tables.protection import mask_tagged_tables, restore_tagged_tables
from defs.text.checkmarks import CheckmarkDecision


def _replace_mark_in_text(text: str, source_token: str, replacement: str) -> str:
    match = next(
        (match for match in _MARK_RE.finditer(text) if match.group(0) == source_token),
        None,
    )
    if match is None:
        return text
    return text[: match.start()] + replacement + text[match.end() :]


def _replace_table_text(
    table_text: str,
    candidates: Sequence[CheckboxCandidate],
    replacements: Mapping[str, CheckmarkDecision],
) -> str:
    """Apply source-cell decisions to a tagged table without taxonomy."""
    lines = table_text.splitlines(keepends=True)
    for candidate in candidates:
        decision = replacements.get(candidate.source_token)
        if decision is None:
            continue
        target_lines = [
            index
            for index, line in enumerate(lines)
            if candidate.source_token in line
            and (
                not candidate.label_text or candidate.label_text.lower() in line.lower()
            )
        ]
        if not target_lines:
            target_lines = [
                index
                for index, line in enumerate(lines)
                if candidate.source_token in line
                and not re.fullmatch(r"\s*[+|:\-=_]+\s*\n?", line)
            ]
        if target_lines:
            index = target_lines[0]
            lines[index] = _replace_mark_in_text(
                lines[index], candidate.source_token, decision.canonical_token
            )
    return "".join(lines)


def _unwrap_pure_yes_no_table(table_text: str) -> str:
    """Remove a wrapper that contained only one rendered Yes/No row."""
    content = re.sub(r"</?TABLE\b[^>]*>", "", table_text, flags=re.IGNORECASE)
    return content.strip()


def _has_pure_yes_no_candidates(
    candidates: Sequence[CheckboxCandidate],
) -> bool:
    return bool(candidates) and all(
        candidate.semantic_key.startswith("table_yes_no:") for candidate in candidates
    )


def apply_cover_checkmark_decisions(
    text: str,
    result: CoverCheckmarkResult,
) -> tuple[str, bool]:
    """Apply resolved source decisions without reclassifying generated tokens."""
    if not result.decisions and not _has_pure_yes_no_candidates(result.candidates):
        return text, False
    original_text = text
    decisions = {
        (decision.source_region, decision.source_token): decision
        for decision in result.decisions
    }
    candidates_by_region: dict[str, list[CheckboxCandidate]] = defaultdict(list)
    for candidate in result.candidates:
        candidates_by_region[candidate.source_region].append(candidate)
    replacements: list[tuple[int, int, str]] = []
    for region, candidates in candidates_by_region.items():
        for candidate in candidates:
            decision = decisions.get((region, candidate.source_token))
            if decision is None or decision.span is None or region.startswith("table-"):
                continue
            start, end = decision.span
            # Spans must land on the token they were extracted from. A stale
            # or foreign-frame span would corrupt unrelated text (including
            # structural table tags) and is dropped instead of applied.
            if text[start:end] != candidate.source_token:
                continue
            replacements.append((start, end, decision.canonical_token))
    for start, end, replacement in sorted(replacements, reverse=True):
        text = text[:start] + replacement + text[end:]

    masked, spans = mask_tagged_tables(text)
    if spans:
        updated_spans = list(spans)
        for region, candidates in candidates_by_region.items():
            if not region.startswith("table-"):
                continue
            match = re.match(r"table-(\d+)", region)
            if match is None:
                continue
            table_index = int(match.group(1))
            if table_index >= len(updated_spans):
                continue
            replacements = {
                candidate.source_token: decisions[(region, candidate.source_token)]
                for candidate in candidates
                if (region, candidate.source_token) in decisions
            }
            table_text = _replace_table_text(
                updated_spans[table_index].text,
                candidates,
                replacements,
            )
            if _has_pure_yes_no_candidates(candidates):
                table_text = _unwrap_pure_yes_no_table(table_text)
            updated_spans[table_index] = type(updated_spans[table_index])(
                updated_spans[table_index].start,
                updated_spans[table_index].end,
                table_text,
            )
        masked = restore_tagged_tables(masked, tuple(updated_spans))
    return masked, masked != original_text


def update_table_geometries(
    table_geometries: Sequence[object],
    result: CoverCheckmarkResult,
) -> tuple[object, ...]:
    """Carry resolved source states into retained table metadata."""
    if not result.decisions:
        return tuple(table_geometries)
    decisions = {
        (decision.source_region, decision.source_token): decision
        for decision in result.decisions
    }
    by_table: dict[int, list[CheckboxCandidate]] = defaultdict(list)
    for candidate in result.candidates:
        match = re.match(r"table-(\d+)/row-(\d+)/column-(\d+)", candidate.source_region)
        if match is not None:
            by_table[int(match.group(1))].append(candidate)
    updated: list[object] = []
    for table_index, geometry in enumerate(table_geometries):
        candidates = by_table.get(table_index, [])
        if not candidates or not hasattr(geometry, "render_result"):
            updated.append(geometry)
            continue
        replacements = {
            candidate.source_token: decisions[
                (candidate.source_region, candidate.source_token)
            ]
            for candidate in candidates
            if (candidate.source_region, candidate.source_token) in decisions
        }
        render_result = geometry.render_result
        ascii_text = _replace_table_text(
            render_result.ascii_text, candidates, replacements
        )
        grid = render_result.resolved_grid
        rows = [list(row) for row in grid.rows]
        for candidate in candidates:
            decision = decisions.get((candidate.source_region, candidate.source_token))
            if decision is None or candidate.row is None or candidate.column is None:
                continue
            if candidate.row >= len(rows) or candidate.column >= len(
                rows[candidate.row]
            ):
                continue
            rows[candidate.row][candidate.column] = _replace_mark_in_text(
                rows[candidate.row][candidate.column],
                candidate.source_token,
                decision.canonical_token,
            )
        new_grid = dataclass_replace(grid, rows=tuple(tuple(row) for row in rows))
        new_result = dataclass_replace(
            render_result,
            ascii_text=ascii_text,
            resolved_grid=new_grid,
        )
        updated.append(dataclass_replace(geometry, render_result=new_result))
    return tuple(updated)


__all__ = ["apply_cover_checkmark_decisions", "update_table_geometries"]
