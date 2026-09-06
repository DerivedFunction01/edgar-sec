"""Candidate group validation and TOC discrimination."""

from __future__ import annotations

from typing import Any

from ..models import (
    PageCandidate,
    PageMarker,
    PageMarkerAction,
    PageMarkerDecision,
    PageMarkerKind,
    PageNumberRun,
    TemplateEvidence,
)
from ..sequence import monotone_fraction
from .dom import _NodeFacts, _sibling_signature


def _group_is_toc_like(ordered: list[dict[str, Any]], facts: _NodeFacts) -> bool:
    signatures = [
        signature
        for item in ordered
        if (signature := _sibling_signature(item["node"], facts)) is not None
    ]
    if len(signatures) < 4:
        return False
    return len(set(signatures)) / len(signatures) > 0.6


def _validate_candidate_groups(
    candidates: list[dict[str, Any]], facts: _NodeFacts
) -> tuple:
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
                valid = True
            if valid and _group_is_toc_like(ordered, facts):
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


__all__ = [
    "_group_is_toc_like",
    "_validate_candidate_groups",
]
