"""Cross-company concept equivalence ranking over atom coordinates."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.taxonomy.defaults import DefaultCoordinate

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
    frozenset({"M_PRETAX", "M_POST_TAX"}),
    frozenset({"M_INCLUDING", "M_EXCLUDING"}),
)

_AGGREGATE_MODIFIER = "M_AGGREGATE"


def _resolve_groups(
    sibling_groups: Iterable[frozenset[str]] | None,
) -> tuple[frozenset[str], ...]:
    """The caller's member sets, or the module-level declared mirror."""
    if sibling_groups is None:
        return SIBLING_GROUPS
    return tuple(frozenset(group) for group in sibling_groups)


def _sibling_swap(left: Atom, right: Atom, groups: tuple[frozenset[str], ...]) -> bool:
    """True when each atom holds exactly one side of a sibling pair."""
    diff = left.modifiers ^ right.modifiers
    if len(diff) != 2 or not any(diff <= group for group in groups):
        return False
    return len(left.modifiers & diff) == 1 and len(right.modifiers & diff) == 1


def _aggregate_scope_widening(left: Atom, right: Atom) -> bool:
    """True when the atoms differ only by the aggregate scope modifier."""
    return left.modifiers ^ right.modifiers == {_AGGREGATE_MODIFIER}


def _classify_detail(
    left: Atom,
    right: Atom,
    groups: tuple[frozenset[str], ...] = SIBLING_GROUPS,
) -> tuple[str, str]:
    """Classify a pair, naming the deciding rule; specific rules first.

    Widening and single-difference pairs are subsumption pairs too, so
    they precede it; every such branch yields NEAR, preserving tiers.
    """
    if left == right:
        return EXACT, "equality"
    if left.head != right.head:
        return UNRELATED, ""
    if _aggregate_scope_widening(left, right):
        return NEAR, "aggregate_widening"
    if len(left.modifiers ^ right.modifiers) == 1:
        return NEAR, "single_modifier_difference"
    if left.is_a(right) or right.is_a(left):
        return NEAR, "subsumption"
    if _sibling_swap(left, right, groups):
        return NEAR, "sibling_swap"
    return UNRELATED, ""


def classify_pair(left: Atom, right: Atom) -> str:
    """Classify two atoms as exact, near (lattice neighbours), or unrelated."""
    return _classify_detail(left, right)[0]


def presumed_atom(
    atom: Atom,
    defaults: Iterable[DefaultCoordinate],
    sibling_groups: Iterable[frozenset[str]] | None = None,
) -> Atom:
    """Apply a presumed coordinate when the atom is silent on the entry's axis.

    The presumed copy exists only for classification and ranking; an atom
    stating any axis value, or matching no entry, is returned unchanged.
    """
    groups = _resolve_groups(sibling_groups)
    for entry in defaults:
        if entry.head != atom.head:
            continue
        group = next(
            (g for g in groups if entry.presumed_modifier in g),
            frozenset(),
        )
        if atom.modifiers & group:
            continue
        if frozenset(atom.modifiers) == frozenset(entry.identity_modifiers):
            return Atom(atom.head, atom.modifiers | {entry.presumed_modifier})
    return atom


@dataclass(frozen=True, slots=True)
class RankedEquivalent:
    """A candidate concept ranked against a target atom."""

    qname: str
    atom: Atom
    tier: str
    modifier_distance: int
    via_default: bool = False
    rule: str = ""


def rank_equivalents(
    target_qname: str,
    target: Atom,
    candidates: Iterable[tuple[str, Atom]],
    defaults: Iterable[DefaultCoordinate] = (),
    sibling_groups: Iterable[frozenset[str]] | None = None,
) -> tuple[RankedEquivalent, ...]:
    """Rank candidate concepts by equivalence tier to the target atom.

    With defaults supplied, distances use presumed atoms and a pair near
    only under presumption is flagged via_default, after evidenced nears.
    """
    groups = _resolve_groups(sibling_groups)
    defaults = tuple(defaults)
    presumed_target = presumed_atom(target, defaults, groups)
    ranked = []
    for qname, atom in candidates:
        if qname == target_qname:
            continue
        tier, rule = _classify_detail(target, atom, groups)
        via_default = False
        presumed = presumed_atom(atom, defaults, groups)
        if tier == UNRELATED and defaults:
            if _classify_detail(presumed_target, presumed, groups)[0] == NEAR:
                tier, via_default, rule = NEAR, True, "via_default"
        if tier == UNRELATED:
            continue
        if defaults:
            distance = len(presumed_target.modifiers ^ presumed.modifiers)
        else:
            distance = len(target.modifiers ^ atom.modifiers)
        ranked.append(
            RankedEquivalent(qname, atom, tier, distance, via_default, rule=rule)
        )
    ranked.sort(
        key=lambda item: (
            0 if item.tier == EXACT else 1,
            1 if item.via_default else 0,
            item.modifier_distance,
            item.qname,
        )
    )
    return tuple(ranked)
