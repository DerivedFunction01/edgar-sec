"""Assignment-stage routing for unclaimed tight-stub carriers.

A carrier left at the residual family is claimed for the family
whose signature terms its caption, lead, and stub carry.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.forms.families.annual.processing import (
    PROFILE as ANNUAL_PROFILE,
)
from edgar_sec.engine.tables.extraction.core.text.normalize import normalize_text
from edgar_sec.engine.tables.extraction.core.registry import RESIDUAL_FAMILY
from edgar_sec.engine.tables.extraction.core.subjects.subject_evidence import load_map
from edgar_sec.engine.tables.extraction.core.typed_rows import TypedTable
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.date_patterns import MONTH_NAMES

PROV_S2_DEPTH2_PRICING = "s2-depth2-pricing:2026-11-17"

ROUTING_FAMILIES = ("equity_statement", "fair_value")

_MONTH_ALT = build_alternation(MONTH_NAMES, auto_escape=True)
CARRIER_RE = re.compile(
    rf"\b(balance|beginning balance)\b[^|\n]{{0,48}}?\b(?:{_MONTH_ALT})\s+1\b",
    re.IGNORECASE,
)


def _derive_terms() -> dict[str, tuple[str, ...]]:
    """The routing families' signature vocabularies, from the map."""
    evidence = load_map()
    return {
        family: tuple(
            sorted({spec.term.lower() for spec in evidence.terms_for(family)})
        )
        for family in ROUTING_FAMILIES
    }


TEXT_TERMS = _derive_terms()


@dataclass(frozen=True, slots=True)
class StubSurfaces:
    """One carrier's priced text surfaces: caption, lead, stub."""

    caption: str
    lead: str
    stub: str


@dataclass(frozen=True, slots=True)
class StubRoutingOutcome:
    """A routed claim: the family, both hit counts, the basis."""

    family: str
    equity_hits: int
    fair_value_hits: int
    detail: str
    provenance: str = PROV_S2_DEPTH2_PRICING


def packet_surfaces(
    caption_stack: tuple[str, ...] | list[str] | None,
    prose_before: str | None,
    table_text: str | None,
) -> StubSurfaces:
    """The priced surfaces of one collected packet, verbatim."""
    stub = "\n".join(line.split("|", 1)[0] for line in (table_text or "").split("\n"))
    return StubSurfaces(
        caption="\n".join(caption_stack or ()),
        lead=prose_before or "",
        stub=stub,
    )


def carrier_text(rows: tuple[tuple[str, ...], ...]) -> str:
    """The geometry rows rendered as the collect's pipe text."""
    return "\n".join(" | ".join(row) for row in rows)


def is_carrier_text(text: str) -> bool:
    """True when the text carries the tight month-stub shape."""
    return CARRIER_RE.search(text) is not None


def table_surfaces(table: TypedTable) -> StubSurfaces:
    """The priced surfaces of one typed table, from its geometry."""
    context = table.context
    stub = "\n".join(row[0] if row else "" for row in context.rows)
    return StubSurfaces(
        caption="\n".join(context.caption_stack),
        lead=context.prose_before or "",
        stub=stub,
    )


def signature_hits(surfaces: StubSurfaces) -> dict[str, tuple[str, ...]]:
    """Distinct signature terms present over caption + lead + stub."""
    text = f"{surfaces.caption}\n{surfaces.lead}\n{surfaces.stub}".lower()
    return {
        family: tuple(term for term in TEXT_TERMS[family] if term in text)
        for family in ROUTING_FAMILIES
    }


def route_family(hits: dict[str, tuple[str, ...]]) -> str | None:
    """The claim a hit profile seats: argmax on duals, else None."""
    hit = [family for family in ROUTING_FAMILIES if hits.get(family)]
    if len(hit) == 1:
        return hit[0]
    if len(hit) == 2:
        first, second = hit
        if len(hits[first]) == len(hits[second]):
            return None
        return first if len(hits[first]) > len(hits[second]) else second
    return None


def evaluate_stub_routing(table: TypedTable) -> StubRoutingOutcome | None:
    """Route one unclaimed table, or None out of shape or scope."""
    section = table.context.section
    if section is None or resolve_alias(section.form) != ANNUAL_PROFILE.family:
        return None
    if not is_carrier_text(carrier_text(table.context.rows)):
        return None
    hits = signature_hits(table_surfaces(table))
    family = route_family(hits)
    if family is None:
        return None
    equity = len(hits["equity_statement"])
    fair_value = len(hits["fair_value"])
    basis = "hit-count argmax" if equity and fair_value else "single signature"
    detail = (
        f"tight-stub carrier routed to {family}: equity_statement "
        f"{equity} terms, fair_value {fair_value} terms ({basis})"
    )
    return StubRoutingOutcome(family, equity, fair_value, detail)


class RoutableResult(Protocol):
    """The classification slice the routing pass reads."""

    family: str
    tier: str
    evidence: tuple


def apply_stub_routing(
    tables: list[TypedTable] | tuple[TypedTable, ...],
    results: list[RoutableResult],
    finish: Callable[..., RoutableResult],
    evidence_type: Callable[..., object],
) -> None:
    """Route unclaimed carriers; the caller injects its seams."""
    for position, table in enumerate(tables):
        result = results[position]
        if result.family != RESIDUAL_FAMILY:
            continue
        if result.tier not in ("residual", "genre_refusal"):
            continue
        outcome = evaluate_stub_routing(table)
        if outcome is None:
            continue
        labels = [normalize_text(row.label) for row in table.rows]
        evidence = list(result.evidence) + [
            evidence_type("stub_routing", outcome.detail, 0.0)
        ]
        results[position] = finish(
            outcome.family, "stub_routing", 0.0, evidence, labels, table
        )
