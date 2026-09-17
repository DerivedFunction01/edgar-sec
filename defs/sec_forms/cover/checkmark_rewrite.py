"""Apply resolved cover checkbox decisions to text and table metadata."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import replace as dataclass_replace

from defs.sec_forms.cover.checkmark_models import (
    CheckboxCandidate,
    CoverCheckmarkResult,
)
from defs.tables.protection import mask_tagged_tables, restore_tagged_tables
from defs.text.checkmarks import (
    CANONICAL_CHECKED,
    CANONICAL_UNCHECKED,
    CHECKMARK_MARK_RE,
    CheckmarkDecision,
    CheckmarkScope,
)


def _replace_mark_in_text(text: str, source_token: str, replacement: str) -> str:
    match = next(
        (
            match
            for match in CHECKMARK_MARK_RE.finditer(text)
            if match.group(0) == source_token
        ),
        None,
    )
    if match is None:
        return text
    start, end = match.start(), match.end()
    if (
        start > 0
        and end < len(text)
        and text[start - 1] == "["
        and text[end] == "]"
        or start > 0
        and end < len(text)
        and text[start - 1] == "("
        and text[end] == ")"
    ):
        start -= 1
        end += 1
    return text[:start] + replacement + text[end:]


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


def _has_labeled_checkmark_candidates(
    candidates: Sequence[CheckboxCandidate],
) -> bool:
    return bool(candidates) and all(c.known_state is not None for c in candidates)


def _has_pure_yes_no_candidates(
    candidates: Sequence[CheckboxCandidate],
) -> bool:
    return bool(candidates) and all(
        candidate.semantic_key.startswith("table_yes_no:") for candidate in candidates
    )


def apply_cover_checkmark_decisions(
    text: str,
    result: CoverCheckmarkResult,
) -> tuple[str, bool, frozenset[int]]:
    """Apply resolved source decisions without reclassifying generated tokens.

    Returns ``(new_text, changed, unwrapped_table_indices)`` where
    ``unwrapped_table_indices`` is the set of *geometry* table indices
    (matching :attr:`~defs.tables.ascii_html.TableGeometry.table_index`)
    whose ``<TABLE>`` tags were physically stripped from the output text.
    Callers must evict those indices from their ``table_geometries`` tuple
    before any subsequent pass that pairs tables by position — otherwise
    the first remaining ``<TABLE>`` block in text will be mis-matched with
    the stale geometry of the table that was just unwrapped.
    """
    if (
        not result.decisions
        and not _has_pure_yes_no_candidates(result.candidates)
        and not _has_labeled_checkmark_candidates(result.candidates)
    ):
        return text, False, frozenset()
    original_text = text
    decisions = {
        (decision.source_region, decision.source_token): decision
        for decision in result.decisions
    }
    for candidate in result.candidates:
        if (
            candidate.known_state is not None
            and (candidate.source_region, candidate.source_token) not in decisions
        ):
            decisions[(candidate.source_region, candidate.source_token)] = (
                CheckmarkDecision(
                    source_token=candidate.source_token,
                    canonical_token=CANONICAL_CHECKED
                    if candidate.known_state == "checked"
                    else CANONICAL_UNCHECKED,
                    state=candidate.known_state,
                    scope=CheckmarkScope.COVER_CONTEXT.value,
                    confidence=1.0,
                    reason="known_state",
                    source_region=candidate.source_region,
                    span=candidate.mark_span,
                )
            )
    candidates_by_region: dict[str, list[CheckboxCandidate]] = defaultdict(list)
    for candidate in result.candidates:
        candidates_by_region[candidate.source_region].append(candidate)
    replacements: list[tuple[int, int, str, str]] = []
    claimed_spans: set[tuple[int, int]] = set()
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
            # Inference may associate one physical mark with several semantic
            # labels (e.g. a single Wingdings "x" matched against every filer
            # status). Each span is rewritten at most once: re-applying the
            # same span slices the already-expanded canonical token into
            # "[X]X]X]" fragments.
            if (start, end) in claimed_spans:
                continue
            claimed_spans.add((start, end))
            replacements.append(
                (start, end, candidate.source_token, decision.canonical_token)
            )
    for start, end, source_token, replacement in sorted(replacements, reverse=True):
        if text[start:end] != source_token:
            continue
        text = text[:start] + replacement + text[end:]

    # Track which geometry table indices are physically unwrapped so the caller
    # can evict them from table_geometries before the next positional pass.
    unwrapped_table_indices: set[int] = set()
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
            if _has_pure_yes_no_candidates(
                candidates
            ) or _has_labeled_checkmark_candidates(candidates):
                table_text = _unwrap_pure_yes_no_table(table_text)
                # Record that this table was physically unwrapped (no longer
                # present as a <TABLE> block in the output text).
                unwrapped_table_indices.add(table_index)
            updated_spans[table_index] = type(updated_spans[table_index])(
                updated_spans[table_index].start,
                updated_spans[table_index].end,
                table_text,
            )
        masked = restore_tagged_tables(masked, tuple(updated_spans))
    return masked, masked != original_text, frozenset(unwrapped_table_indices)


def update_table_geometries(
    table_geometries: Sequence[object],
    result: CoverCheckmarkResult,
    unwrapped_table_indices: frozenset[int] = frozenset(),
) -> tuple[object, ...]:
    """Carry resolved source states into retained table metadata.

    If ``unwrapped_table_indices`` is supplied, any geometry whose
    :attr:`~defs.tables.ascii_html.TableGeometry.table_index` appears in
    that set is dropped from the result — its ``<TABLE>`` block was
    physically removed from the text by
    :func:`apply_cover_checkmark_decisions` and must not be passed to any
    subsequent positional-pairing pass such as :func:`clean_cover_tables`.
    """
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
    for geometry in table_geometries:
        # Use the stable table_index attribute to look up candidates and to
        # determine whether this geometry was physically unwrapped.
        geom_id = getattr(geometry, "table_index", None)
        if geom_id is not None and geom_id in unwrapped_table_indices:
            # Table was unwrapped by apply_cover_checkmark_decisions; it is no
            # longer present as a <TABLE> block in the output text.
            continue
        candidates = by_table.get(geom_id if geom_id is not None else -1, [])
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
