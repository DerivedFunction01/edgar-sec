"""Cross-company concept equivalence ranking over atom coordinates."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from edgar_sec.engine.xbrl.schema.atoms import Atom

EXACT = "exact"
NEAR = "near"
UNRELATED = "unrelated"

# Modifier sets that classify the same position mutually exclusively;
# swapping one sibling for another keeps two atoms near, never exact.
SIBLING_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"M_AVAILABLE_FOR_SALE", "M_HELD_TO_MATURITY"}),
    frozenset({"M_ACCOUNTS_PAYABLE", "M_ACCRUED_LIABILITY"}),
    frozenset({"M_COMMON", "M_PREFERRED"}),
    frozenset({"V_NET", "V_GROSS"}),
    frozenset({"V_BASIC", "V_DILUTED"}),
    frozenset({"M_CURRENT", "M_NONCURRENT"}),
)

_AGGREGATE_MODIFIER = "M_AGGREGATE"


def _sibling_swap(left: Atom, right: Atom) -> bool:
    """True when each atom holds exactly one side of a sibling pair."""
    diff = left.modifiers ^ right.modifiers
    if len(diff) != 2 or not any(diff <= group for group in SIBLING_GROUPS):
        return False
    return len(left.modifiers & diff) == 1 and len(right.modifiers & diff) == 1


def _aggregate_scope_widening(left: Atom, right: Atom) -> bool:
    """True when the atoms differ only by the aggregate scope modifier."""
    return left.modifiers ^ right.modifiers == {_AGGREGATE_MODIFIER}


def classify_pair(left: Atom, right: Atom) -> str:
    """Classify two atoms as exact, near (lattice neighbours), or unrelated."""
    if left == right:
        return EXACT
    if left.head != right.head:
        return UNRELATED
    if left.is_a(right) or right.is_a(left):
        return NEAR
    if _aggregate_scope_widening(left, right):
        return NEAR
    if len(left.modifiers ^ right.modifiers) == 1:
        return NEAR
    if _sibling_swap(left, right):
        return NEAR
    return UNRELATED


@dataclass(frozen=True, slots=True)
class RankedEquivalent:
    """A candidate concept ranked against a target atom."""

    qname: str
    atom: Atom
    tier: str
    modifier_distance: int


def rank_equivalents(
    target_qname: str,
    target: Atom,
    candidates: Iterable[tuple[str, Atom]],
) -> tuple[RankedEquivalent, ...]:
    """Rank candidate concepts by equivalence tier to the target atom."""
    ranked = []
    for qname, atom in candidates:
        if qname == target_qname:
            continue
        tier = classify_pair(target, atom)
        if tier == UNRELATED:
            continue
        distance = len(target.modifiers ^ atom.modifiers)
        ranked.append(RankedEquivalent(qname, atom, tier, distance))
    ranked.sort(
        key=lambda item: (
            0 if item.tier == EXACT else 1,
            item.modifier_distance,
            item.qname,
        )
    )
    return tuple(ranked)
