"""Member subsumption specimens from panel filings and synthetic arcs."""

import json

import pyarrow.parquet as pq

from edgar_sec.engine.xbrl.evidence.subsumption import MemberSubsumption
from edgar_sec.engine.xbrl.schema.models import DefinitionArc
from edgar_sec.engine.xbrl.storage.storage import definition_arcs_from_arrow_table
from tests.support import bundle_dir

_EQUITY_AXIS = "us-gaap:StatementEquityComponentsAxis"
_SEGMENT_AXES = (
    "srt:StatementGeographicalAxis",
    "us-gaap:RestructuringCostAndReserveAxis",
    "srt:ProductOrServiceAxis",
    "us-gaap:FiniteLivedIntangibleAssetsByMajorClassAxis",
    "us-gaap:StatementBusinessSegmentsAxis",
)
_PANEL = (
    "amat_2024_10k",
    "cost_2024_10k",
    "cvx_2024_10k",
    "ge_2024_10k",
    "hon_2024_10k",
    "orcl_2024_10k",
)
_DM = "http://xbrl.org/int/dim/arcrole/domain-member"


def _service(folder: str) -> MemberSubsumption:
    table = pq.read_table(bundle_dir(folder) / "definition_arcs.parquet")
    return MemberSubsumption(definition_arcs_from_arrow_table(table))


def test_member_subsumed_by_aggregate_panel_specimens() -> None:
    """A summed member under an aggregate member is subsumed by it."""
    ge = _service("ge_2024_10k")
    assert ge.is_subsumed(
        _EQUITY_AXIS, "us-gaap:RetainedEarningsMember", "us-gaap:ParentMember"
    )
    assert ge.is_subsumed(
        _EQUITY_AXIS,
        "us-gaap:AccumulatedTranslationAdjustmentMember",
        "us-gaap:ParentMember",
    )
    assert not ge.is_subsumed(
        _EQUITY_AXIS, "us-gaap:ParentMember", "us-gaap:RetainedEarningsMember"
    )
    cost = _service("cost_2024_10k")
    assert cost.is_subsumed(
        _EQUITY_AXIS, "us-gaap:CommonStockMember", "us-gaap:ParentMember"
    )


def test_default_member_subsumes_tree_and_only_itself() -> None:
    """The declared default is the undimensioned total for its axis."""
    ge = _service("ge_2024_10k")
    default = ge.default_member(_EQUITY_AXIS)
    assert default == "us-gaap:EquityComponentDomain"
    assert ge.is_subsumed(_EQUITY_AXIS, "us-gaap:ParentMember", default)
    assert ge.is_subsumed(_EQUITY_AXIS, default, default)
    assert not ge.is_subsumed(_EQUITY_AXIS, default, "us-gaap:ParentMember")


def test_panel_axes_answer_every_fact_member_pair() -> None:
    """No exercised (axis, member) pair on the panel abstains."""
    for folder in _PANEL:
        service = _service(folder)
        rows = pq.read_table(bundle_dir(folder) / "facts.parquet").to_pylist()
        members: dict[str, set[str]] = {}
        for row in rows:
            for axis, member in json.loads(row["dimensions_json"]).items():
                members.setdefault(axis, set()).add(member)
        for axis in (_EQUITY_AXIS, *_SEGMENT_AXES):
            used = members.get(axis, set())
            for member in used:
                assert service.is_subsumed(axis, member, member) is True
                for other in used:
                    assert service.is_subsumed(axis, member, other) is not None


def test_unusable_arc_and_arcless_axis_abstain() -> None:
    """A usable=false edge carries no subsumption; an arc-less axis abstains."""
    arcs = (
        DefinitionArc(
            "ex:Axis", "ex:Domain", "http://xbrl.org/int/dim/arcrole/dimension-domain"
        ),
        DefinitionArc(
            "ex:Axis", "ex:Domain", "http://xbrl.org/int/dim/arcrole/dimension-default"
        ),
        DefinitionArc("ex:Domain", "ex:AggregateMember", _DM),
        DefinitionArc("ex:AggregateMember", "ex:LeafMember", _DM, usable=False),
    )
    service = MemberSubsumption(arcs)
    assert service.is_subsumed("ex:Axis", "ex:LeafMember", "ex:AggregateMember") is None
    assert service.is_subsumed("ex:Axis", "ex:AggregateMember", "ex:Domain")
    assert service.is_subsumed("ex:MissingAxis", "ex:LeafMember", "ex:Domain") is None
    assert MemberSubsumption(()).is_subsumed("ex:Axis", "ex:A", "ex:B") is None


def test_frontier_drops_subsumed_members() -> None:
    """The frontier keeps only members no other listed member subsumes."""
    ge = _service("ge_2024_10k")
    members = (
        "us-gaap:RetainedEarningsMember",
        "us-gaap:ParentMember",
        "us-gaap:NoncontrollingInterestMember",
    )
    assert ge.frontier(_EQUITY_AXIS, members) == (
        "us-gaap:ParentMember",
        "us-gaap:NoncontrollingInterestMember",
    )
