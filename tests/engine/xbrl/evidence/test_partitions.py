"""Partition classification over synthetic member sets, one per class."""

from edgar_sec.engine.xbrl.evidence.partitions import (
    CLEAN_PARTITION,
    INCOMPLETE,
    NESTED_MEMBERS,
    OVERLAPPING_PARTITIONS,
    OVER_UNEXPLAINED,
    classify_partitions,
)
from edgar_sec.engine.xbrl.evidence.subsumption import MemberSubsumption
from edgar_sec.engine.xbrl.schema.models import DefinitionArc

_AXIS = "x:Axis"
_DM = "http://xbrl.org/int/dim/arcrole/domain-member"
_DD = "http://xbrl.org/int/dim/arcrole/dimension-domain"
_DF = "http://xbrl.org/int/dim/arcrole/dimension-default"


def _subsumption(edges: list[tuple[str, str]]) -> MemberSubsumption:
    arcs = [
        DefinitionArc(_AXIS, "x:Domain", _DD),
        DefinitionArc(_AXIS, "x:Domain", _DF),
    ]
    arcs.extend(DefinitionArc(parent, child, _DM) for parent, child in edges)
    return MemberSubsumption(tuple(arcs))


def test_flat_overlap_two_disjoint_partitions() -> None:
    """Index-specimen shape: a category pair and its detail both total."""
    values = {"x:Product": 450.0, "x:ServiceOther": 550.0}
    values.update({f"x:Detail{i}": 100.0 for i in range(10)})
    result = classify_partitions(values, 1000.0)
    assert result.kind == OVERLAPPING_PARTITIONS
    assert result.basis == "arcless"
    assert result.subsumed == ()
    assert result.enumeration_capped is False
    assert result.partitions == (
        tuple(f"x:Detail{i}" for i in range(10)),
        ("x:Product", "x:ServiceOther"),
    )


def test_nested_members_decided_by_arcs_alone() -> None:
    """An aggregate member replacing its children is the nested class."""
    subsumption = _subsumption(
        [
            ("x:Domain", "x:All"),
            ("x:All", "x:Alpha"),
            ("x:All", "x:Beta"),
        ]
    )
    values = {"x:All": 1000.0, "x:Alpha": 600.0, "x:Beta": 400.0}
    result = classify_partitions(values, 1000.0, axis=_AXIS, subsumption=subsumption)
    assert result.kind == NESTED_MEMBERS
    assert result.basis == "arcs"
    assert result.partitions == (("x:All",),)
    assert result.subsumed == ("x:Alpha", "x:Beta")


def test_clean_partition_same_sign() -> None:
    """Members summing exactly to the total are one clean partition."""
    result = classify_partitions({"x:A": 600.0, "x:B": 400.0}, 1000.0)
    assert result.kind == CLEAN_PARTITION
    assert result.partitions == (("x:A", "x:B"),)
    assert result.enumeration_capped is False


def test_clean_partition_with_cancelling_member() -> None:
    """A mixed-sign set whose only complete subset is itself is clean."""
    result = classify_partitions({"x:A": 1200.0, "x:B": -200.0}, 1000.0)
    assert result.kind == CLEAN_PARTITION
    assert result.partitions == (("x:A", "x:B"),)


def test_clean_partition_ignores_zero_members() -> None:
    """A zero member joins no partition and does not disturb the class."""
    result = classify_partitions({"x:A": 600.0, "x:B": 400.0, "x:Z": 0.0}, 1000.0)
    assert result.kind == CLEAN_PARTITION
    assert result.partitions == (("x:A", "x:B"),)


def test_incomplete_members_fall_short() -> None:
    """Members short of the total, with no complete subset, are incomplete."""
    result = classify_partitions({"x:A": 600.0, "x:B": 300.0}, 1000.0)
    assert result.kind == INCOMPLETE
    assert result.partitions == ()


def test_single_partition_with_junk_remainder_is_unexplained() -> None:
    """One true partition plus an unexplained extra member is not clean."""
    result = classify_partitions({"x:A": 600.0, "x:B": 400.0, "x:C": 30.0}, 1000.0)
    assert result.kind == OVER_UNEXPLAINED
    assert result.partitions == (("x:A", "x:B"),)


def test_shared_member_ambiguity_is_unexplained() -> None:
    """Complete subsets sharing a member cannot both be served."""
    result = classify_partitions({"x:A": 60.0, "x:B": 40.0, "x:C": 60.0}, 100.0)
    assert result.kind == OVER_UNEXPLAINED
    assert result.partitions == (("x:A", "x:B"), ("x:B", "x:C"))


def test_over_member_cap_degrades_with_cap_recorded() -> None:
    """Past the member bound the class degrades; the cap is recorded."""
    values = {f"x:M{i}": 100.0 for i in range(33)}
    result = classify_partitions(values, 1000.0)
    assert result.kind == OVER_UNEXPLAINED
    assert result.enumeration_capped is True
    assert result.partitions == ()


def test_over_member_cap_under_sum_is_incomplete() -> None:
    """A capped positive set short of the total is provably incomplete."""
    values = {f"x:M{i}": 10.0 for i in range(33)}
    result = classify_partitions(values, 1000.0)
    assert result.kind == INCOMPLETE
    assert result.enumeration_capped is True


def test_level_sets_tried_past_the_bound() -> None:
    """A capped mixed-sign set is decided by its tree level sets."""
    edges = [("x:Domain", f"x:L{i}") for i in range(33)]
    subsumption = _subsumption(edges)
    values = {f"x:L{i}": 100.0 for i in range(32)}
    values["x:L32"] = -2200.0
    result = classify_partitions(values, 1000.0, axis=_AXIS, subsumption=subsumption)
    assert result.enumeration_capped is True
    assert result.partitions == (tuple(sorted(values)),)
    assert result.kind == OVER_UNEXPLAINED


def test_large_overlap_resolves_within_the_raised_bound() -> None:
    """A 23-member overlap is proven by the directed complement search."""
    values = {"x:A1": 600.0, "x:A2": 400.0, "x:B0": 200.0}
    values.update({f"x:B{i}": 40.0 for i in range(1, 21)})
    result = classify_partitions(values, 1000.0)
    assert result.kind == OVERLAPPING_PARTITIONS
    assert any(
        set(part).isdisjoint(result.partitions[0]) for part in result.partitions[1:]
    )
