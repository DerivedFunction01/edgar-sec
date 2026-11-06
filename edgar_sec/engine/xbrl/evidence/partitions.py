"""Partition classification of filed axis members against a reported total."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from edgar_sec.engine.xbrl.evidence.subsumption import MemberSubsumption
from edgar_sec.engine.xbrl.solve.identities import identity_verified

CLEAN_PARTITION = "clean_partition"
OVERLAPPING_PARTITIONS = "overlapping_partitions"
NESTED_MEMBERS = "nested_members"
INCOMPLETE = "incomplete"
OVER_UNEXPLAINED = "over_unexplained"

_BASIS_ARCS = "arcs"
_BASIS_ARCLESS = "arcless"

MAX_ENUM_MEMBERS = 32
MAX_ENUM_NODES = 10_000_000
_MAX_PARTITIONS = 16
_MAX_CANDIDATES = 64
_TOLERANCE = 1.0


@dataclass(frozen=True, slots=True)
class PartitionClassification:
    """How one group's filed members relate to its reported total.

    partitions holds every complete partition found, finest first;
    subsumed names members the definition arcs exclude declaratively.
    """

    kind: str
    partitions: tuple[tuple[str, ...], ...] = ()
    subsumed: tuple[str, ...] = ()
    basis: str = _BASIS_ARCLESS
    enumeration_capped: bool = False


def classify_partitions(
    values: Mapping[str, float],
    total: float,
    *,
    axis: str | None = None,
    subsumption: MemberSubsumption | None = None,
) -> PartitionClassification:
    """Classify one group's collapsed member values against its total.

    Authority order: the arc frontier decides nesting, exact-sum subset
    analysis decides the rest, and the plain sum is the floor.
    """
    filed = tuple(sorted(values))
    frontier: tuple[str, ...] | None = None
    subsumed: tuple[str, ...] = ()
    basis = _BASIS_ARCLESS
    if subsumption is not None and axis is not None:
        basis = _BASIS_ARCS
        result = subsumption.frontier(axis, filed)
        if result is not None:
            frontier = result
            keep = set(result)
            subsumed = tuple(member for member in filed if member not in keep)
    if not filed:
        return PartitionClassification(INCOMPLETE, basis=basis)
    if frontier is not None and subsumed:
        frontier_sum = sum(values[member] for member in frontier)
        if identity_verified(total, frontier_sum):
            return PartitionClassification(
                NESTED_MEMBERS,
                partitions=(tuple(sorted(frontier)),),
                subsumed=subsumed,
                basis=basis,
            )
    work = frontier if frontier is not None else filed
    work_sum = sum(values[member] for member in work)
    nonzero = tuple(member for member in work if values[member] != 0.0)
    if _unique_clean(values, work, total, work_sum):
        return PartitionClassification(
            CLEAN_PARTITION,
            partitions=(tuple(sorted(work)),),
            subsumed=subsumed,
            basis=basis,
        )
    found, capped = _enumerate_partitions(values, nonzero, total)
    if capped and not _has_disjoint_pair(found):
        found = found + _level_partitions(values, work, total, axis, subsumption)
    family = _disjoint_family(found)
    partitions = tuple(dict.fromkeys([*family, *_ordered(found)]))[:_MAX_PARTITIONS]
    if _has_disjoint_pair(partitions):
        kind = OVERLAPPING_PARTITIONS
    elif len(partitions) == 1 and set(partitions[0]) == set(nonzero) and not capped:
        kind = CLEAN_PARTITION
    elif partitions:
        kind = OVER_UNEXPLAINED
    elif work_sum < total - _TOLERANCE:
        kind = INCOMPLETE
    else:
        kind = OVER_UNEXPLAINED
    return PartitionClassification(
        kind,
        partitions=partitions,
        subsumed=subsumed,
        basis=basis,
        enumeration_capped=capped,
    )


def _unique_clean(
    values: Mapping[str, float],
    work: tuple[str, ...],
    total: float,
    work_sum: float,
) -> bool:
    """Same-sign, zero-free sets summing to the total partition uniquely."""
    if not identity_verified(total, work_sum):
        return False
    signs = {values[member] > 0 for member in work if values[member] != 0.0}
    if len(signs) != 1:
        return False
    return all(values[member] != 0.0 for member in work)


def _sorted_partitions(
    found: tuple[tuple[str, ...], ...],
) -> tuple[tuple[str, ...], ...]:
    """Distinct partitions, finest first."""
    distinct = dict.fromkeys(found)
    return tuple(sorted(distinct, key=lambda part: (-len(part), part)))


def _ordered(
    found: tuple[tuple[str, ...], ...],
) -> tuple[tuple[str, ...], ...]:
    """Distinct partitions, finest first, capped in count."""
    return _sorted_partitions(found)[:_MAX_PARTITIONS]


def _disjoint_family(
    partitions: tuple[tuple[str, ...], ...],
) -> tuple[tuple[str, ...], ...]:
    """A maximal pairwise-disjoint subfamily, finest first."""
    family: list[tuple[str, ...]] = []
    used: set[str] = set()
    for part in _sorted_partitions(partitions):
        members = set(part)
        if members & used:
            continue
        family.append(part)
        used |= members
    return tuple(family)


def _has_disjoint_pair(partitions: tuple[tuple[str, ...], ...]) -> bool:
    """Whether two recorded partitions share no member."""
    return len(_disjoint_family(partitions)) >= 2


def _collect_partitions(
    values: Mapping[str, float],
    members: list[str],
    total: float,
    state: dict[str, object],
    want: int,
) -> list[tuple[str, ...]]:
    """Branch-and-bound subset search over one member list, budget-shared."""
    vals = [values[member] for member in members]
    count = len(members)
    suffix = [0.0] * (count + 1)
    for index in range(count - 1, -1, -1):
        suffix[index] = suffix[index + 1] + abs(vals[index])
    found: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()
    chosen: list[str] = []

    def visit(index: int, current: float) -> None:
        if state["capped"] or len(found) >= want:
            return
        state["nodes"] = int(state["nodes"]) + 1
        if int(state["nodes"]) > MAX_ENUM_NODES:
            state["capped"] = True
            return
        if chosen and identity_verified(total, current):
            part = tuple(sorted(chosen))
            if part not in seen:
                seen.add(part)
                found.append(part)
                if len(found) >= want:
                    return
        if index == count:
            return
        if abs(total - current) - suffix[index] > _TOLERANCE:
            return
        chosen.append(members[index])
        visit(index + 1, current + vals[index])
        chosen.pop()
        visit(index + 1, current)

    visit(0, 0.0)
    return found


def _enumerate_partitions(
    values: Mapping[str, float],
    work: tuple[str, ...],
    total: float,
) -> tuple[tuple[tuple[str, ...], ...], bool]:
    """Subset analysis: a first partition, its complement, then the record.

    The complement search proves or refutes a disjoint second partition
    directly, so symmetric subset floods cannot starve the verdict.
    """
    members = sorted(work, key=lambda member: (-abs(values[member]), member))
    if len(members) > MAX_ENUM_MEMBERS:
        return (), True
    state: dict[str, object] = {"nodes": 0, "capped": False}
    first = _collect_partitions(values, members, total, state, 1)
    if not first:
        return (), bool(state["capped"])
    pivot = set(first[0])
    complement = [member for member in members if member not in pivot]
    second = _collect_partitions(values, complement, total, state, 1)
    if not second:
        rest = _collect_partitions(values, members, total, state, _MAX_CANDIDATES)
        capped = bool(state["capped"]) or len(rest) >= _MAX_CANDIDATES
        return tuple(dict.fromkeys(rest)), capped
    rest = _collect_partitions(values, members, total, state, _MAX_CANDIDATES)
    capped = bool(state["capped"]) or len(rest) >= _MAX_CANDIDATES
    found = [first[0], second[0], *rest]
    return tuple(dict.fromkeys(found)), capped


def _level_partitions(
    values: Mapping[str, float],
    work: tuple[str, ...],
    total: float,
    axis: str | None,
    subsumption: MemberSubsumption | None,
) -> tuple[tuple[str, ...], ...]:
    """Per-depth level sets of the axis tree tried as partition candidates."""
    if subsumption is None or axis is None:
        return ()
    levels: dict[int, list[str]] = {}
    for member in work:
        rank = 0
        for other in work:
            if other != member and subsumption.is_subsumed(axis, member, other):
                rank += 1
        levels.setdefault(rank, []).append(member)
    candidates: list[tuple[str, ...]] = []
    for rank in sorted(levels):
        group = tuple(sorted(levels[rank]))
        if identity_verified(total, sum(values[member] for member in group)):
            candidates.append(group)
    return tuple(candidates)
