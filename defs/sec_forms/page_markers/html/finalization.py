"""HTML analysis enrichment, finalization, and decision application."""

from __future__ import annotations

from dataclasses import replace
from itertools import pairwise
from typing import Any

from ..models import (
    PageMarker,
    PageMarkerAction,
    PageMarkerAnalysis,
    PageMarkerDecision,
    PageMarkerTerminalState,
    PageNumberRun,
    TemplateEvidence,
)
from ..sequence import unify_alternating_runs
from .discovery import _candidate_nodes
from .dom import _flatten_recursive_pages, _NodeFacts, _resolve_path
from .probes import (
    _RECIPE_CACHE,
    _RECIPE_CACHE_LIMIT,
    _RECIPE_REJECTED,
    _html_recipe_signature,
    _recipe_fingerprint,
    _recipe_learn,
)
from .recovery import (
    _family_extents,
    _recover_between_nodes,
    _recover_run_gaps,
    _region_reports,
)
from .validation import _validate_candidate_groups


def enrich_html_analysis(
    analysis: PageMarkerAnalysis | None,
    soup: object,
    *,
    allow_letter_number: bool = True,
    source_text: str,
) -> PageMarkerAnalysis:
    base = analysis or PageMarkerAnalysis(
        (), (), (), representation="html", source_text=source_text
    )
    _flatten_recursive_pages(soup)
    facts = _NodeFacts()
    signature = _html_recipe_signature(source_text)
    candidates: list[dict[str, Any]] | None = None
    if signature:
        for profile in reversed(_RECIPE_CACHE.get(signature, ())):
            fingerprint = _recipe_fingerprint(profile)
            rejected_key = (signature, fingerprint)
            if rejected_key in _RECIPE_REJECTED:
                continue
            targeted = _candidate_nodes(
                soup,
                allow_letter_number=allow_letter_number,
                source_text=source_text,
                facts=facts,
                recipe_profile=profile,
            )
            trial = _validate_candidate_groups(targeted, facts)
            if trial[0] and trial[2]:
                candidates = targeted
                markers, decisions, runs, templates, unresolved = trial
                break
            _RECIPE_REJECTED[rejected_key] = None
            while len(_RECIPE_REJECTED) > _RECIPE_CACHE_LIMIT:
                _RECIPE_REJECTED.popitem(last=False)
    if candidates is None:
        candidates = _candidate_nodes(
            soup,
            allow_letter_number=allow_letter_number,
            source_text=source_text,
            facts=facts,
        )
        markers, decisions, runs, templates, unresolved = _validate_candidate_groups(
            candidates, facts
        )
        _recipe_learn(signature, markers, candidates)
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
    by_path = {item["path"]: item for item in candidates if item.get("path")}
    recovered: list[dict[str, Any]] = []
    for run in runs:
        ordered = sorted(run.candidates, key=lambda item: item.node_path)
        for left, right in pairwise(ordered):
            missing = right.value - left.value - 1
            if not 1 <= missing <= 64:
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
    from ..ascii import analyze_page_markers

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
    "_finalize_html_analysis",
    "apply_html_page_decisions",
    "enrich_html_analysis",
    "refresh_html_analysis",
]
