"""Specimen tests for the plan statement factories on XbrlStatements.

Pins are filed totals from the probe bundles, corroborated against the
bundles' own facts; discrepancies pin the filed data's own postures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.engine.xbrl.solve.query import QueryStatus
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.support import bundle_dir, fixture_path

_NET_ROOT = "us-gaap-ebp:EmployeeBenefitPlanNetAssetAvailableForBenefit"
_CHANGES_ROOT = (
    "us-gaap-ebp:EmployeeBenefitPlanChangeInNetAssetAvailableForBenefitIncreaseDecrease"
)

# folder -> (net values by year, changes values by year, net nodes, changes nodes)
_SAMPLE = {
    "msft_2025_11k": (
        {"2024": 65627337124.0, "2025": 77820483784.0},
        {"2025": 12193146660.0},
        12,
        10,
    ),
    "abt_2025_11k": (
        {"2024": 15725269000.0, "2025": 17841016000.0},
        {"2025": 2115747000.0},
        13,
        13,
    ),
    "r_2025_11k": (
        {"2023": 1945506000.0, "2024": 2325827000.0, "2025": 2656585000.0},
        {"2024": 291720000.0, "2025": 330758000.0},
        12,
        14,
    ),
    "key_2025_11k": (
        {"2023": 3726984216.0, "2024": 4129131619.0, "2025": 4677863774.0},
        {"2024": 402147403.0, "2025": 548732155.0},
        8,
        13,
    ),
    "duk_2025_11k": (
        {"2024": 11269744000.0, "2025": 12583488000.0},
        {"2025": 1313744000.0},
        8,
        13,
    ),
}

_FACADES: dict[str, Xbrl] = {}
_TAXONOMY = None


def _facade(folder: str) -> Xbrl:
    """One cached facade per probe bundle folder."""
    global _TAXONOMY
    if _TAXONOMY is None:
        _TAXONOMY = load_domain_taxonomy()
    if folder not in _FACADES:
        path = fixture_path(f"xbrl/probe/{folder}")
        _FACADES[folder] = Xbrl.from_bundle(Path(path), _TAXONOMY)
    return _FACADES[folder]


@pytest.mark.parametrize("folder", sorted(_SAMPLE))
def test_plan_factories_serve_sample(folder: str) -> None:
    """Both factories serve the filed roots, values, and face sizes."""
    net_values, changes_values, net_nodes, changes_nodes = _SAMPLE[folder]
    statements = _facade(folder).statements
    net = statements.plan_net_assets()
    changes = statements.plan_changes()
    assert net.status is QueryStatus.REPORTED
    assert changes.status is QueryStatus.REPORTED
    assert net.root is not None and net.root.concept_qname == _NET_ROOT
    assert changes.root is not None and changes.root.concept_qname == _CHANGES_ROOT
    assert net.root.values == net_values
    assert changes.root.values == changes_values
    assert len(net.nodes) == net_nodes
    assert len(changes.nodes) == changes_nodes


@pytest.mark.parametrize("folder", sorted(_SAMPLE))
def test_plan_reconciliation(folder: str) -> None:
    """Latest net delta equals the changes total, per filed totals."""
    statements = _facade(folder).statements
    net = statements.plan_net_assets()
    changes = statements.plan_changes()
    assert net.root is not None and changes.root is not None
    years = sorted(net.root.values)
    delta = net.root.values[years[-1]] - net.root.values[years[-2]]
    assert delta == changes.root.values[max(changes.root.values)]


@pytest.mark.parametrize(
    ("folder", "factory", "discrepancy"),
    [
        ("msft_2025_11k", "plan_changes", 6116277.0),
        ("r_2025_11k", "plan_net_assets", 1000.0),
    ],
)
def test_plan_antichain_filed_postures(
    folder: str, factory: str, discrepancy: float
) -> None:
    """Two graphs carry filed-data discrepancies, pinned as filed: an
    unarced decrease total, and rounding inside the filer's components."""
    view = getattr(_facade(folder).statements, factory)()
    outcome = view.verify_antichain()
    assert not outcome.is_valid
    assert outcome.discrepancy == discrepancy


@pytest.mark.parametrize(
    "folder", [f for f in sorted(_SAMPLE) if f not in ("msft_2025_11k", "r_2025_11k")]
)
def test_plan_antichain_valid(folder: str) -> None:
    """The remaining sample graphs verify exactly against filed totals."""
    statements = _facade(folder).statements
    assert statements.plan_net_assets().verify_antichain().is_valid
    assert statements.plan_changes().verify_antichain().is_valid


def test_plan_member_selection() -> None:
    """Default serves the largest plan; an explicit member serves its own."""
    statements = _facade("abt_2025_11k").statements
    default = statements.plan_net_assets()
    assert default.root is not None
    assert default.root.values["2025"] == 17841016000.0
    small = statements.plan_net_assets(member_qname="abt:EBP002Member")
    assert small.status is QueryStatus.REPORTED
    assert small.root is not None
    assert small.root.values == {"2024": 243299000.0, "2025": 271092000.0}
    small_changes = statements.plan_changes(member_qname="abt:EBP002Member")
    assert small_changes.root is not None
    assert small_changes.root.values == {"2025": 27793000.0}
    refused = statements.plan_net_assets(member_qname="abt:NopeMember")
    assert refused.status is QueryStatus.UNAVAILABLE


def test_plan_year_argument() -> None:
    """A year-scoped net-assets view serves that year's filed total."""
    view = _facade("msft_2025_11k").statements.plan_net_assets(year=2024)
    assert view.root is not None
    assert view.root.value == 65627337124.0


@pytest.mark.parametrize("folder", ["msft_2026_10q", "bsrr_2024_10k", "bsrr_2024_10ka"])
def test_plan_absence_on_probe_corporate_filings(folder: str) -> None:
    """Corporate probe filings serve the standard absence posture."""
    statements = _facade(folder).statements
    for view in (statements.plan_net_assets(), statements.plan_changes()):
        assert view.status is QueryStatus.UNAVAILABLE
        assert view.message == "No statement of this type is reported in this filing."


def test_plan_absence_on_seed_annual() -> None:
    """A seed-corpus corporate annual serves the absence posture."""
    facade = Xbrl.from_bundle(bundle_dir("msft_2024_10k"), load_domain_taxonomy())
    for view in (
        facade.statements.plan_net_assets(),
        facade.statements.plan_changes(),
    ):
        assert view.status is QueryStatus.UNAVAILABLE
