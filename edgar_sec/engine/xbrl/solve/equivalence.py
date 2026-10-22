"""Cross-company concept equivalence ranking over atom coordinates."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.taxonomy.defaults import DefaultCoordinate
from edgar_sec.engine.xbrl.taxonomy.heads_modifiers import SiblingGroup

EXACT = "exact"
NEAR = "near"
UNRELATED = "unrelated"

GENERALIZATION = "generalization"
SPECIALIZATION = "specialization"

# Modifier sets that classify the same position mutually exclusively;
# swapping one sibling for another keeps two atoms near, never exact.
# Mirrors the sibling_groups.json declaration (names, members, scopes).
SIBLING_GROUPS: tuple[SiblingGroup, ...] = (
    SiblingGroup(
        "SECURITIES_CLASSIFICATION",
        ("M_AVAILABLE_FOR_SALE", "M_HELD_TO_MATURITY"),
        "compoundable",
    ),
    SiblingGroup(
        "OPERATING_LIABILITY_IDENTITY",
        ("M_ACCOUNTS_PAYABLE", "M_ACCRUED_LIABILITY"),
        "compoundable",
    ),
    SiblingGroup("STOCK_CLASS", ("M_COMMON", "M_PREFERRED"), "compoundable"),
    SiblingGroup("VALUATION_PRESENTATION", ("V_NET", "V_GROSS"), "compoundable"),
    SiblingGroup("EPS_BASIS", ("V_BASIC", "V_DILUTED"), "exclusive"),
    SiblingGroup("MATURITY_HORIZON", ("M_CURRENT", "M_NONCURRENT"), "compoundable"),
    SiblingGroup("TAX_BASIS", ("M_PRETAX", "M_POST_TAX"), "exclusive"),
    SiblingGroup("SCOPE_POLARITY", ("M_INCLUDING", "M_EXCLUDING"), "exclusive"),
)

_AGGREGATE_MODIFIER = "M_AGGREGATE"


def _resolve_groups(
    sibling_groups: Iterable[SiblingGroup | Iterable[str]] | None,
) -> tuple[SiblingGroup, ...]:
    """The caller's groups, or the module-level declared mirror.

    Bare member sets normalize to anonymous unscoped groups, preserving
    the behaviour bare callers have always had.
    """
    if sibling_groups is None:
        return SIBLING_GROUPS
    return tuple(
        group
        if isinstance(group, SiblingGroup)
        else SiblingGroup("", tuple(group), "compoundable")
        for group in sibling_groups
    )


def _sibling_swap(left: Atom, right: Atom, groups: tuple[SiblingGroup, ...]) -> bool:
    """True when each atom holds exactly one side of an admitted sibling pair.

    The difference must sit inside one single group and that group's
    scope must admit the pair's head and shared modifiers.
    """
    diff = left.modifiers ^ right.modifiers
    if len(diff) != 2:
        return False
    if len(left.modifiers & diff) != 1 or len(right.modifiers & diff) != 1:
        return False
    shared = left.modifiers & right.modifiers
    return any(
        diff <= frozenset(group.members) and group.swap_admitted(left.head, shared)
        for group in groups
    )


def _aggregate_scope_widening(left: Atom, right: Atom) -> bool:
    """True when the atoms differ only by the aggregate scope modifier."""
    return left.modifiers ^ right.modifiers == {_AGGREGATE_MODIFIER}


def _classify_detail(
    left: Atom,
    right: Atom,
    groups: tuple[SiblingGroup, ...] = SIBLING_GROUPS,
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


def _subsumption_direction(target: Atom, candidate: Atom) -> str:
    """Name a pair's subsumption direction; empty when neither subsumes.

    Generalization means the candidate strictly subsumes the target;
    specialization means the target strictly subsumes the candidate.
    """
    if target.is_a(candidate) and not candidate.is_a(target):
        return GENERALIZATION
    if candidate.is_a(target) and not target.is_a(candidate):
        return SPECIALIZATION
    return ""


def _axis_members(
    groups: tuple[SiblingGroup, ...], entry: DefaultCoordinate
) -> frozenset[str]:
    """The member set of the axis a default names.

    Named groups resolve by name: a modifier holding several memberships
    cannot make the silence test depend on group order. Anonymous
    groups fall back to first membership.
    """
    for group in groups:
        if group.group == entry.axis:
            return frozenset(group.members)
    for group in groups:
        if entry.presumed_modifier in group.members:
            return frozenset(group.members)
    return frozenset()


def presumed_atom(
    atom: Atom,
    defaults: Iterable[DefaultCoordinate],
    sibling_groups: Iterable[SiblingGroup | Iterable[str]] | None = None,
) -> Atom:
    """Apply a presumed coordinate when the atom is silent on the entry's axis.

    The presumed copy exists only for classification and ranking; an atom
    stating any axis value, or matching no entry, is returned unchanged.
    """
    groups = _resolve_groups(sibling_groups)
    for entry in defaults:
        if entry.head != atom.head:
            continue
        if atom.modifiers & _axis_members(groups, entry):
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
    residual_intent_count: int = 0
    residual_total_count: int = 0
    direction: str = ""


def rank_equivalents(
    target_qname: str,
    target: Atom,
    candidates: Iterable[tuple[str, Atom]],
    defaults: Iterable[DefaultCoordinate] = (),
    sibling_groups: Iterable[SiblingGroup | Iterable[str]] | None = None,
    residual_counts: Mapping[str, tuple[int, int]] | None = None,
) -> tuple[RankedEquivalent, ...]:
    """Rank candidate concepts by equivalence tier to the target atom.

    With defaults supplied, distances use presumed atoms and a pair near
    only under presumption is flagged via_default, after evidenced nears.
    """
    groups = _resolve_groups(sibling_groups)
    defaults = tuple(defaults)
    counts = residual_counts or {}
    presumed_target = presumed_atom(target, defaults, groups)
    ranked = []
    for qname, atom in candidates:
        if qname == target_qname:
            continue
        tier, rule = _classify_detail(target, atom, groups)
        via_default = False
        presumed = presumed_atom(atom, defaults, groups)
        direction_target, direction_atom = target, atom
        if tier == UNRELATED and defaults:
            if _classify_detail(presumed_target, presumed, groups)[0] == NEAR:
                tier, via_default, rule = NEAR, True, "via_default"
                direction_target, direction_atom = presumed_target, presumed
        if tier == UNRELATED:
            continue
        if defaults:
            distance = len(presumed_target.modifiers ^ presumed.modifiers)
        else:
            distance = len(target.modifiers ^ atom.modifiers)
        intent, total = counts.get(qname, (0, 0))
        ranked.append(
            RankedEquivalent(
                qname,
                atom,
                tier,
                distance,
                via_default,
                rule=rule,
                residual_intent_count=intent,
                residual_total_count=total,
                direction=_subsumption_direction(direction_target, direction_atom),
            )
        )
    ranked.sort(
        key=lambda item: (
            0 if item.tier == EXACT else 1,
            1 if item.via_default else 0,
            item.modifier_distance,
            item.residual_intent_count,
            item.residual_total_count,
            item.qname,
        )
    )
    return tuple(ranked)
