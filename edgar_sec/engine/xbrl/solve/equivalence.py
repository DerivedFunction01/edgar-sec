"""Cross-company concept equivalence ranking over atom coordinates."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.taxonomy.defaults import DefaultCoordinate
from edgar_sec.engine.xbrl.taxonomy.heads_modifiers import (
    SiblingGroup,
    load_sibling_groups,
)

EXACT = "exact"
NEAR = "near"
UNRELATED = "unrelated"

GENERALIZATION = "generalization"
SPECIALIZATION = "specialization"

_AGGREGATE_MODIFIER = "M_AGGREGATE"
_TEXT_MODIFIER = "M_TEXT_NODE"
_HORIZON_AXIS = "MATURITY_HORIZON"
_HORIZON_FALLBACK = frozenset({"M_CURRENT", "M_NONCURRENT"})

_DEFAULT_GROUPS: tuple[SiblingGroup, ...] | None = None


def _default_groups() -> tuple[SiblingGroup, ...]:
    """The shipped sibling-group declaration, loaded once on first use."""
    global _DEFAULT_GROUPS
    if _DEFAULT_GROUPS is None:
        _DEFAULT_GROUPS = load_sibling_groups(
            resolve_xbrl_paths().default_sibling_groups_path
        )
    return _DEFAULT_GROUPS


def _resolve_groups(
    sibling_groups: Iterable[SiblingGroup | Iterable[str]] | None,
) -> tuple[SiblingGroup, ...]:
    """The caller's groups, or the shipped sibling-group declaration.

    Bare member sets normalize to anonymous unscoped groups, preserving
    the behaviour bare callers have always had.
    """
    if sibling_groups is None:
        return _default_groups()
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


def _text_barrier(left: Atom, right: Atom) -> bool:
    """True when exactly one atom carries the text coordinate."""
    return (_TEXT_MODIFIER in left.modifiers) != (_TEXT_MODIFIER in right.modifiers)


def _classify_detail(
    left: Atom,
    right: Atom,
    groups: tuple[SiblingGroup, ...] | None = None,
) -> tuple[str, str]:
    """Classify a pair, naming the deciding rule; specific rules first.

    Widening and single-difference pairs are subsumption pairs too, so
    they precede it; every such branch yields NEAR, preserving tiers.
    """
    if groups is None:
        groups = _default_groups()
    if left == right:
        return EXACT, "equality"
    if left.head != right.head:
        return UNRELATED, ""
    if _text_barrier(left, right):
        return UNRELATED, "text_barrier"
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

    Named groups resolve by name, never by order; anonymous groups
    fall back to first membership.
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


def _horizon_members(groups: tuple[SiblingGroup, ...]) -> frozenset[str]:
    """The MATURITY_HORIZON axis members declared among the groups."""
    for group in groups:
        if group.group == _HORIZON_AXIS:
            return frozenset(group.members)
    return _HORIZON_FALLBACK


def _filing_local(
    atom: Atom,
    derived_horizon: str | None,
    placement_horizon: str | None,
    groups: tuple[SiblingGroup, ...],
) -> Atom:
    """Apply the filing-local rung; higher rungs' silence is its entry condition."""
    if placement_horizon is None:
        return atom
    members = _horizon_members(groups)
    if atom.modifiers & members:
        return atom
    if derived_horizon is not None:
        return atom
    if placement_horizon not in members:
        return atom
    return Atom(atom.head, atom.modifiers | {placement_horizon})


def presumed_atom_filing_local(
    atom: Atom,
    derived_horizon: str | None,
    placement_horizon: str | None,
    sibling_groups: Iterable[SiblingGroup | Iterable[str]] | None = None,
) -> Atom:
    """Presume a placement-derived horizon when name and derived are silent.

    An atom stating any horizon member, or a set derived horizon, is
    returned unchanged: evidence never outranks a higher rung.
    """
    return _filing_local(
        atom, derived_horizon, placement_horizon, _resolve_groups(sibling_groups)
    )


def _ladder_atom(
    atom: Atom,
    defaults: tuple[DefaultCoordinate, ...],
    groups: tuple[SiblingGroup, ...],
    derived_horizon: str | None,
    placement_horizon: str | None,
) -> tuple[Atom, str]:
    """One side's fully presumed atom and the rung that supplied it."""
    members = _horizon_members(groups)
    if not atom.modifiers & members:
        if derived_horizon is not None and derived_horizon in members:
            return Atom(atom.head, atom.modifiers | {derived_horizon}), "derived"
        placed = _filing_local(atom, derived_horizon, placement_horizon, groups)
        if placed != atom:
            return placed, "filing_local"
    presumed = presumed_atom(atom, defaults, groups)
    if presumed != atom:
        return presumed, "default"
    return atom, ""


@dataclass(frozen=True, slots=True)
class LadderClassification:
    """One pair's classification under the full presumption ladder."""

    tier: str
    rule: str
    via_default: bool
    via_filing_local: bool
    modifier_distance: int
    direction: str


def classify_ladder_pair(
    target: Atom,
    candidate: Atom,
    defaults: Iterable[DefaultCoordinate] = (),
    sibling_groups: Iterable[SiblingGroup | Iterable[str]] | None = None,
    *,
    target_derived_horizon: str | None = None,
    candidate_derived_horizon: str | None = None,
    target_placement_horizon: str | None = None,
    candidate_placement_horizon: str | None = None,
) -> LadderClassification:
    """Classify a pair on stated atoms, then on fully presumed atoms.

    A pair NEAR only under presumption names its weakest mediating
    rung: via_filing_local above via_default, derived by its own rule.
    """
    groups = _resolve_groups(sibling_groups)
    defaults = tuple(defaults)
    tier, rule = _classify_detail(target, candidate, groups)
    target_atom, target_rung = _ladder_atom(
        target, defaults, groups, target_derived_horizon, target_placement_horizon
    )
    candidate_atom, candidate_rung = _ladder_atom(
        candidate,
        defaults,
        groups,
        candidate_derived_horizon,
        candidate_placement_horizon,
    )
    via_default = False
    via_filing_local = False
    direction_target, direction_atom = target, candidate
    if tier == UNRELATED:
        ladder_tier, ladder_rule = _classify_detail(target_atom, candidate_atom, groups)
        if ladder_tier == NEAR:
            tier = NEAR
            via_filing_local = "filing_local" in (target_rung, candidate_rung)
            via_default = "default" in (target_rung, candidate_rung)
            if via_default:
                rule = "via_default"
            elif via_filing_local:
                rule = "via_filing_local"
            else:
                rule = ladder_rule
            direction_target, direction_atom = target_atom, candidate_atom
    if defaults or any(
        value is not None
        for value in (
            target_derived_horizon,
            candidate_derived_horizon,
            target_placement_horizon,
            candidate_placement_horizon,
        )
    ):
        distance = len(target_atom.modifiers ^ candidate_atom.modifiers)
    else:
        distance = len(target.modifiers ^ candidate.modifiers)
    return LadderClassification(
        tier=tier,
        rule=rule,
        via_default=via_default,
        via_filing_local=via_filing_local,
        modifier_distance=distance,
        direction=_subsumption_direction(direction_target, direction_atom),
    )


@dataclass(frozen=True, slots=True)
class RankedEquivalent:
    """A candidate concept ranked against a target atom."""

    qname: str
    atom: Atom
    tier: str
    modifier_distance: int
    via_default: bool = False
    via_filing_local: bool = False
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
    *,
    target_derived_horizon: str | None = None,
    target_placement_horizon: str | None = None,
    derived_horizons: Mapping[str, str | None] | None = None,
    placement_horizons: Mapping[str, str | None] | None = None,
) -> tuple[RankedEquivalent, ...]:
    """Rank candidate concepts by equivalence tier to the target atom.

    Distances use fully presumed atoms; a pair near only under a weaker
    rung sorts after stronger rungs: evidenced, filing-local, default.
    """
    groups = _resolve_groups(sibling_groups)
    defaults = tuple(defaults)
    counts = residual_counts or {}
    derived = derived_horizons or {}
    placements = placement_horizons or {}
    ranked = []
    for qname, atom in candidates:
        if qname == target_qname:
            continue
        result = classify_ladder_pair(
            target,
            atom,
            defaults,
            groups,
            target_derived_horizon=target_derived_horizon,
            candidate_derived_horizon=derived.get(qname),
            target_placement_horizon=target_placement_horizon,
            candidate_placement_horizon=placements.get(qname),
        )
        if result.tier == UNRELATED:
            continue
        intent, total = counts.get(qname, (0, 0))
        ranked.append(
            RankedEquivalent(
                qname,
                atom,
                result.tier,
                result.modifier_distance,
                result.via_default,
                result.via_filing_local,
                rule=result.rule,
                residual_intent_count=intent,
                residual_total_count=total,
                direction=result.direction,
            )
        )
    ranked.sort(
        key=lambda item: (
            0 if item.tier == EXACT else 1,
            2 if item.via_default else 1 if item.via_filing_local else 0,
            item.modifier_distance,
            item.residual_intent_count,
            item.residual_total_count,
            item.qname,
        )
    )
    return tuple(ranked)


__all__ = [
    "EXACT",
    "GENERALIZATION",
    "NEAR",
    "SPECIALIZATION",
    "UNRELATED",
    "LadderClassification",
    "RankedEquivalent",
    "classify_ladder_pair",
    "classify_pair",
    "presumed_atom",
    "presumed_atom_filing_local",
    "rank_equivalents",
]
