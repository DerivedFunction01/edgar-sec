"""Bottomline candidate selection from atom coordinates and calc arcs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import (
    CalculationArc,
    XbrlFact,
    qname_local,
)

_BOTTOMLINE_HEADS = frozenset({"H_INCOME", "H_PROFIT", "H_MARGIN", "H_LOSS"})
_BOTTOMLINE_SLICES = frozenset(
    {
        "M_NONCONTROLLING_INTEREST",
        "M_COMMON",
        "V_BASIC",
        "V_DILUTED",
        "M_DISCONTINUED",
    }
)


def is_bottomline(atom: Atom) -> bool:
    """Bottomline marking: the net modifier, or a bare income head."""
    mods = set(atom.modifiers)
    return "M_NET_BOTTOMLINE" in mods or (atom.head == "H_INCOME" and mods <= {"V_NET"})


def bottomline_rank(atom: Atom | None, qname: str) -> tuple[int, int, int, str] | None:
    """Rank a bottomline candidate; slice concepts are not candidates."""
    if atom is None or atom.head not in _BOTTOMLINE_HEADS:
        return None
    mods = set(atom.modifiers)
    if "M_COMPREHENSIVE" in mods or "M_OCI" in mods:
        return None
    if not is_bottomline(atom) or _BOTTOMLINE_SLICES & mods:
        return None
    group = 0 if "M_NET_BOTTOMLINE" in mods else 1
    return (group, len(mods), len(qname_local(qname)), qname)


def bottomline_candidate(
    atoms: Mapping[str, Atom | None],
    facts: Sequence[XbrlFact],
    arcs: Sequence[CalculationArc],
) -> str | None:
    """Best-ranked bottomline concept among all arc concepts."""
    duration = {f.concept_qname for f in facts if f.period_type == "duration"}
    concepts = {a.parent_qname for a in arcs} | {a.child_qname for a in arcs}
    ranks = [
        rank
        for concept in concepts & duration
        if (rank := bottomline_rank(atoms.get(concept), concept)) is not None
    ]
    return min(ranks)[3] if ranks else None
