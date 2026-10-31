"""Statement-view audit: built-in presets reproduce Step 3 battery facts."""

from __future__ import annotations

import pyarrow as pa

from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.discovery.cohort import load_canonical_union_cohort
from edgar_sec.engine.xbrl.discovery.placement_slices import placement_slices
from edgar_sec.engine.xbrl.review.battery import BATTERY_SET, BatteryEntry
from edgar_sec.engine.xbrl.schema.models import FilingXbrl, LinkbaseBundle
from edgar_sec.engine.xbrl.solve.antichain import AntiChainValidator
from edgar_sec.engine.xbrl.solve.identities import verify_eps_identity
from edgar_sec.engine.xbrl.solve.scoping import FactScope
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.pipelines.xbrl_review.bundles import load_filing

_ACCESSIONS = {
    "0000950170-24-087843",  # MSFT FY2024
    "0001193125-16-662209",  # MSFT FY2016 (vintage panel, span collisions)
    "0000320193-19-000119",  # AAPL FY2019 (vintage panel, span collisions)
    "0000018230-25-000008",  # CAT (face bottom line is bare ProfitLoss)
    "0000200406-25-000038",  # JNJ (disposal-group gross-profit shadow)
    "0001652044-25-000014",  # GOOGL (bottom line is a calc leaf)
    "0000104169-24-000056",  # WMT (precision-duplicate cash facts)
    "0001306965-25-000007",  # SHEL (IFRS)
    "0001370368-25-000004",  # NVS (IFRS, extension discontinued slice)
    "0000019617-25-000270",  # JPM (liabilities/equity-total shadowing)
    "0000070858-14-000012",  # BAC FY2013 (vintage panel)
    "0000070858-16-000137",  # BAC FY2015 (cash is no calc descendant)
    "0000070858-25-000139",  # BAC FY2024 (XVA detail is calc-isolated)
    "0000937966-25-000009",  # ASML FY2024 (cash is calc-isolated)
}
_SLICE_ACCESSIONS = _ACCESSIONS | {
    "0000070858-20-000011",  # BAC FY2019 (revenue in segment roles only)
    "0001326160-25-000072",  # DUK (incl-tax revenue in disaggregation only)
}
_EPS = {"us-gaap:EarningsPerShareBasic", "us-gaap:EarningsPerShareDiluted"}
# EPS facts carry no calculation arcs, so no statement graph contains
# them; they reproduce through the query surface, not statement views.
_NODE_EXCLUDED = _EPS | {
    # The cash rollup identity is presentational for JPM: the rollup
    # concept is no calculation child in any of the three statements.
    "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    # The balance-sheet identity total is a sibling root, never a
    # calculation descendant of the assets root.
    "us-gaap:LiabilitiesAndStockholdersEquity",
}
# Pinned by entry: the bare-head series headlines the largest filed
# revenue total; the battery value is a narrower filed total (guard below).
_SERIES_PINNED = {
    "wmt-revenue": 648_125_000_000.0,
    "duk-revenue-including-assessed-tax": 30_357_000_000.0,
    "bac-2013-revenue": 89_801_000_000.0,
    "bac-2019-revenue": 91_839_000_000.0,
    "bac-2021-revenue": 89_540_000_000.0,
    "bac-2023-revenue": 99_148_000_000.0,
}
# Pinned by entry: the filing's calc linkbase gives the concept no
# descendant path, so no statement graph can contain it (guard below).
_NODE_EXCLUDED_ENTRIES = {
    "bac-xva-derivative-assets",
    "bac-2015-cash",
    "asml-2024-cash",
}
# Pinned by entry: placed only in disclosure-details roles, never
# under a statement root, so placement yields no statement slice.
_SLICE_PINNED = {
    "duk-revenue-including-assessed-tax",
    "bac-2019-revenue",
    "asml-2024-cash",
}
_SLICE_BY_KIND = {
    "gross_profit": "IncomeStatement",
    "operating_income": "IncomeStatement",
    "net_income": "IncomeStatement",
    "revenue": "IncomeStatement",
    "total_assets": "BalanceSheet",
    "total_liabilities": "BalanceSheet",
    "total_equity": "BalanceSheet",
    "cfo": "CashFlow",
    "cfi": "CashFlow",
    "cff": "CashFlow",
}
_SLICE_EXTRA = {
    "us-gaap:CashAndCashEquivalentsAtCarryingValue": "BalanceSheet",
    "us-gaap:RetainedEarningsAccumulatedDeficit": "BalanceSheet",
    "ifrs-full:CashAndCashEquivalents": "BalanceSheet",
}

_CFO = {
    "us-gaap:NetCashProvidedByUsedInOperatingActivities",
    "us-gaap:NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
}
_CFI = {
    "us-gaap:NetCashProvidedByUsedInInvestingActivities",
    "us-gaap:NetCashProvidedByUsedInInvestingActivitiesContinuingOperations",
}
_CFF = {
    "us-gaap:NetCashProvidedByUsedInFinancingActivities",
    "us-gaap:NetCashProvidedByUsedInFinancingActivitiesContinuingOperations",
}
_REVENUES = {
    "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax",
    "us-gaap:Revenues",
    "us-gaap:SalesRevenueNet",
    "us-gaap:RevenuesNetOfInterestExpense",
    "ifrs-full:Revenue",
    "ifrs-full:RevenueFromSaleOfGoods",
}
_NET = {"us-gaap:NetIncomeLoss", "us-gaap:ProfitLoss", "ifrs-full:ProfitLoss"}


def _kind(qname: str) -> str | None:
    if qname == "us-gaap:GrossProfit":
        return "gross_profit"
    if qname == "us-gaap:OperatingIncomeLoss":
        return "operating_income"
    if qname in _NET:
        return "net_income"
    if qname in ("us-gaap:Assets", "ifrs-full:Assets"):
        return "total_assets"
    if qname == "us-gaap:Liabilities":
        return "total_liabilities"
    if qname.startswith("us-gaap:StockholdersEquity"):
        return "total_equity"
    if qname in _CFO:
        return "cfo"
    if qname in _CFI:
        return "cfi"
    if qname in _CFF:
        return "cff"
    if qname in _REVENUES:
        return "revenue"
    return None


_FACADES: dict[str, Xbrl] = {}
_GRAPHS: dict[tuple[str, str], dict[str, object]] = {}
_LOADED: dict[str, object] = {}


def _loaded(accession: str):
    if accession not in _LOADED:
        seeds = {str(s.accession): s for s in load_canonical_union_cohort()}
        _LOADED[accession] = load_filing(seeds[accession])
    return _LOADED[accession]


def _facade(accession: str) -> Xbrl:
    if accession not in _FACADES:
        seeds = {str(s.accession): s for s in load_canonical_union_cohort()}
        seed = seeds[accession]
        loaded = load_filing(seed)
        bundle = FilingXbrl(
            accession=AccessionNumber.from_any(accession),
            cik=Cik(int(seed.cik)),
            facts=loaded.facts,
            linkbases=LinkbaseBundle(
                calculation_arcs=loaded.calc_arcs,
                presentation_arcs=loaded.pres_arcs,
                declarations=tuple(loaded.declarations.values()),
            ),
        )
        _FACADES[accession] = Xbrl(bundle, load_domain_taxonomy())
    return _FACADES[accession]


def _graphs(accession: str, year: str) -> dict[str, object]:
    key = (accession, year)
    if key not in _GRAPHS:
        facade = _facade(accession)
        _GRAPHS[key] = {
            "income": facade.statements.income_statement(year=year).graph,
            "balance": facade.statements.balance_sheet(year=year).graph,
            "cash": facade.statements.cash_flow_statement(year=year).graph,
        }
    return _GRAPHS[key]


def _nodes(graph: object) -> dict:
    nodes = dict(graph.nodes)  # type: ignore[attr-defined]
    for attr in (
        "gross_profit_graph",
        "operating_income_graph",
        "assets_graph",
        "liabilities_graph",
        "equity_graph",
        "operating",
        "investing",
        "financing",
    ):
        sub = getattr(graph, attr, None)
        if sub is not None:
            nodes.update(sub.nodes)
    return nodes


def _entries() -> list[BatteryEntry]:
    return [
        entry
        for entry in BATTERY_SET
        if entry.accession in _ACCESSIONS and not entry.dimensions
    ]


def test_statement_graphs_reproduce_battery_facts() -> None:
    """Every in-scope battery fact is a statement-graph node at its value."""
    failures = []
    for entry in _entries():
        if entry.qname in _NODE_EXCLUDED or entry.entry_id in _NODE_EXCLUDED_ENTRIES:
            continue
        year = (entry.instant or entry.end)[:4]
        graphs = _graphs(entry.accession, year)
        hits = [
            node.value
            for graph in graphs.values()
            if (node := _nodes(graph).get(entry.qname)) is not None
        ]
        if entry.expected_value not in hits:
            failures.append(f"{entry.entry_id}: node values {hits}")
    assert not failures, "\n".join(failures)


def test_node_pins_are_calc_isolated_in_their_filings() -> None:
    """Pinned node entries are calculation descendants of nothing."""
    for entry in _entries():
        if entry.entry_id not in _NODE_EXCLUDED_ENTRIES:
            continue
        loaded = _loaded(entry.accession)
        reach = AntiChainValidator.build_reachability_map(
            [(a.parent_qname, a.child_qname, a.weight) for a in loaded.calc_arcs]
        )
        descendants = set().union(*reach.values()) if reach else set()
        assert entry.qname not in descendants, entry.entry_id


def test_placement_slices_reproduce_battery_facts() -> None:
    """Classified battery concepts carry their statement slice by role."""
    taxonomy = load_domain_taxonomy()
    assert taxonomy.token_lexicon is not None
    slices_by_acc: dict[str, dict[str, set[str]]] = {}

    def slices_for(accession: str) -> dict[str, set[str]]:
        if accession not in slices_by_acc:
            loaded = _loaded(accession)
            table = pa.table(
                {
                    "parent_qname": [a.parent_qname for a in loaded.pres_arcs],
                    "child_qname": [a.child_qname for a in loaded.pres_arcs],
                    "role_uri": [a.role_uri or "" for a in loaded.pres_arcs],
                }
            )
            slices_by_acc[accession] = placement_slices(table, taxonomy.token_lexicon)
        return slices_by_acc[accession]

    failures = []
    for entry in BATTERY_SET:
        if entry.accession not in _SLICE_ACCESSIONS or entry.dimensions:
            continue
        expected = _SLICE_BY_KIND.get(_kind(entry.qname) or "") or _SLICE_EXTRA.get(
            entry.qname
        )
        if expected is None:
            continue
        got = slices_for(entry.accession).get(entry.qname, set())
        if entry.entry_id in _SLICE_PINNED:
            if got & {"BalanceSheet", "IncomeStatement", "CashFlow", "Equity"}:
                failures.append(f"{entry.entry_id}: pinned, got {sorted(got)}")
        elif expected not in got:
            failures.append(f"{entry.entry_id}: {expected} not in {sorted(got)}")
    assert not failures, "\n".join(failures)


def test_statement_scalars_reproduce_battery_facts() -> None:
    """Headline graph scalars and financials series match the battery."""
    failures = []
    for entry in _entries():
        kind = _kind(entry.qname)
        if kind is None:
            continue
        year = (entry.instant or entry.end)[:4]
        graphs = _graphs(entry.accession, year)
        inc, bal, cash = graphs["income"], graphs["balance"], graphs["cash"]
        graph_scalar = {
            "gross_profit": inc.gross_profit,  # type: ignore[attr-defined]
            "operating_income": inc.operating_income,  # type: ignore[attr-defined]
            "net_income": inc.net_income,  # type: ignore[attr-defined]
            "total_assets": bal.total_assets,  # type: ignore[attr-defined]
            "total_liabilities": bal.total_liabilities,  # type: ignore[attr-defined]
            "total_equity": bal.total_equity,  # type: ignore[attr-defined]
            "cfo": cash.cfo,  # type: ignore[attr-defined]
            "cfi": cash.cfi,  # type: ignore[attr-defined]
            "cff": cash.cff,  # type: ignore[attr-defined]
        }.get(kind)
        if kind != "revenue" and graph_scalar != entry.expected_value:
            failures.append(
                f"{entry.entry_id}: graph {kind} {graph_scalar} != {entry.expected_value}"
            )
        if entry.entry_id in _SERIES_PINNED:
            continue
        fin = _facade(entry.accession).financials
        series = {
            "revenue": fin.revenue_series,
            "gross_profit": fin.gross_profit_series,
            "operating_income": fin.operating_income_series,
            "net_income": fin.net_income_series,
            "total_assets": fin.total_assets_series,
            "total_liabilities": fin.total_liabilities_series,
            "total_equity": fin.total_equity_series,
            "cfo": fin.operating_cash_flow_series,
        }.get(kind)
        if series is not None and series.get(year) != entry.expected_value:
            failures.append(
                f"{entry.entry_id}: series {kind} {series.get(year)} "
                f"!= {entry.expected_value}"
            )
    assert not failures, "\n".join(failures)


def _battery(entry_id: str) -> BatteryEntry:
    return next(e for e in BATTERY_SET if e.entry_id == entry_id)


def test_cash_rollforward_reproduces_bac_rollup_specimen() -> None:
    """BAC rollforward verifies, tied to its two balance-sheet lines."""
    entry = _battery("bac-2024-cash-rollup")
    view = _facade(entry.accession).financials.cash_rollforward
    assert view.end == entry.expected_value
    assert view.beginning == 333_073_000_000.0
    assert view.net_change == -42_959_000_000.0
    assert view.rollforward_verified is True
    assert view.balance_sheet_verified is True
    assert view.balance_sheet_total == entry.expected_value
    assert {c.concept_qname for c in view.components} == {
        "us-gaap:CashAndDueFromBanks",
        "us-gaap:InterestBearingDepositsInBanks",
    }


def test_cash_rollforward_serves_jpm_rollup_without_calc_arcs() -> None:
    """JPM rollforward verifies; its balance-sheet tie reports the gap."""
    entry = _battery("jpm-cash")
    view = _facade(entry.accession).financials.cash_rollforward
    assert view.end == entry.expected_value
    assert view.beginning == 624_151_000_000.0
    assert view.net_change == -154_834_000_000.0
    assert view.rollforward_verified is True
    assert view.balance_sheet_total == 27_500_000_000.0
    assert view.balance_sheet_verified is False
    assert view.balance_sheet_discrepancy == 441_817_000_000.0


def test_cash_rollforward_reproduces_msft_specimen() -> None:
    """MSFT rollforward verifies, tied to its carrying-value line."""
    entry = _battery("msft-cash")
    view = _facade(entry.accession).financials.cash_rollforward
    assert view.end == entry.expected_value
    assert view.beginning == 34_704_000_000.0
    assert view.net_change == -16_389_000_000.0
    assert view.rollforward_verified is True
    assert view.balance_sheet_verified is True


def test_segment_breakdown_reproduces_aapl_china_specimen() -> None:
    """AAPL business-segment revenue verifies, including the China member."""
    entry = _battery("aapl-segment-revenue-china")
    axis, member = entry.dimensions[0]
    view = _facade(entry.accession).financials.segment_breakdown(
        concept_qname=entry.qname, axis_qname=axis
    )
    assert view.total == _battery("aapl-revenue").expected_value
    assert view.values_by_member[member] == entry.expected_value
    assert len(view.members) == 5
    assert view.member_sum == view.total
    assert view.verified is True
    assert view.discrepancy == 0.0
    default = _facade(entry.accession).financials.segment_breakdown()
    assert default.concept_qname == entry.qname
    assert default.axis_qname == axis
    assert default.verified is True


def test_segment_breakdown_reproduces_msft_specimen() -> None:
    """MSFT business-segment revenue verifies across its three segments."""
    view = _facade("0000950170-24-087843").financials.segment_breakdown(
        concept_qname="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        axis_qname="us-gaap:StatementBusinessSegmentsAxis",
    )
    assert view.total == 245_122_000_000.0
    assert view.member_sum == view.total
    assert view.verified is True
    assert view.values_by_member == {
        "msft:ProductivityAndBusinessProcessesMember": 77_728_000_000.0,
        "msft:IntelligentCloudMember": 105_362_000_000.0,
        "msft:MorePersonalComputingMember": 62_032_000_000.0,
    }


def test_segment_breakdown_reports_googl_gap() -> None:
    """GOOGL segment revenue falls short of the total; the gap is reported."""
    view = _facade("0001652044-25-000014").financials.segment_breakdown(
        concept_qname="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        axis_qname="us-gaap:StatementBusinessSegmentsAxis",
    )
    assert view.total == 350_018_000_000.0
    assert view.member_sum == 349_807_000_000.0
    assert view.verified is False
    assert view.discrepancy == 211_000_000.0


# Pinned by entry: the filing files no diluted weighted-share fact,
# so the EPS identity route has no denominator and cannot verify it.
_EPS_PINNED = {"xom-eps-diluted"}


def test_eps_specimens_dispositioned_by_the_identity_route() -> None:
    """Every EPS specimen verifies by identity, or is pinned with evidence."""
    for entry in BATTERY_SET:
        if entry.qname not in _EPS:
            continue
        loaded = _loaded(entry.accession)
        scope = FactScope(
            accession=entry.accession, start_date=entry.start, end_date=entry.end
        )
        outcome = verify_eps_identity(
            loaded.facts, diluted=entry.qname.endswith("Diluted"), scope=scope
        )
        if entry.entry_id in _EPS_PINNED:
            assert outcome is None, entry.entry_id
            assert "pinned" in entry.verification, entry.entry_id
            filed = {fact.concept_qname for fact in loaded.facts}
            assert (
                "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding" not in filed
            )
            basic = {
                fact.value
                for fact in loaded.facts
                if fact.concept_qname == "us-gaap:EarningsPerShareBasic"
                and not fact.dimensions
                and fact.start_date == entry.start
                and fact.end_date == entry.end
            }
            assert basic == {entry.expected_value}, entry.entry_id
            continue
        assert outcome is not None, entry.entry_id
        assert outcome.passed, f"{entry.entry_id}: {outcome}"
        assert outcome.lhs_value == entry.expected_value, entry.entry_id
        assert outcome.tolerance == 0.005, entry.entry_id
        assert "EPS identity route" in entry.verification, entry.entry_id


def test_calc_isolated_node_pins_use_the_provenance_route() -> None:
    """Non-EPS calc-isolated pins carry facts.parquet provenance, not a calc route."""
    for entry_id in _NODE_EXCLUDED_ENTRIES:
        entry = _battery(entry_id)
        assert entry.verification.startswith("facts.parquet"), entry_id


def test_series_pins_headline_the_larger_filed_revenue_total() -> None:
    """Pinned series entries headline a larger filed revenue fact."""
    for entry in BATTERY_SET:
        if entry.entry_id not in _SERIES_PINNED:
            continue
        pinned = _SERIES_PINNED[entry.entry_id]
        assert pinned > entry.expected_value, entry.entry_id
        year = (entry.instant or entry.end)[:4]
        series = _facade(entry.accession).financials.revenue_series
        assert series.get(year) == pinned, entry.entry_id
        filed = {
            fact.value for fact in _loaded(entry.accession).facts if not fact.dimensions
        }
        assert pinned in filed, entry.entry_id


def test_level3_rollforward_reproduces_met_transfers_specimen() -> None:
    """MET corporate debt rollforward verifies, transfers-in tied to battery."""
    entry = _battery("met-level3-transfers-in")
    axis, member = entry.dimensions[0]
    view = _facade(entry.accession).financials.level3_rollforward(
        axis_qname=axis, member_qname=member
    )
    assert view.transfers_in == entry.expected_value
    assert view.opening == 28_345_000_000.0
    assert view.closing == 26_505_000_000.0
    assert view.gains_earnings == -143_000_000.0
    assert view.gains_oci == -1_177_000_000.0
    assert view.purchases == 5_587_000_000.0
    assert view.sales == 2_236_000_000.0
    assert view.transfers_out == 4_103_000_000.0
    assert view.verified is True
    assert view.discrepancy == 0.0
    assert view.missing_components == ()


def test_level3_rollforward_verifies_met_derivative_class() -> None:
    """MET net-derivative rollforward verifies from a negative opening."""
    view = _facade("0001099219-25-000044").financials.level3_rollforward(
        axis_qname="us-gaap:DerivativeInstrumentRiskAxis",
        member_qname="met:NetDerivativesMember",
    )
    assert view.opening == -143_000_000.0
    assert view.closing == 5_000_000.0
    assert view.verified is True
    assert view.discrepancy == 0.0


def test_level3_rollforward_verifies_bac_asset_and_liability_classes() -> None:
    """BAC asset and liability classes verify; liability gains flip sign."""
    accession = _battery("bac-2024-cash-rollup").accession
    asset = _facade(accession).financials.level3_rollforward(
        axis_qname="us-gaap:FairValueByAssetClassAxis",
        member_qname="us-gaap:DebtSecuritiesMember",
    )
    assert asset.opening == 376_000_000.0
    assert asset.closing == 611_000_000.0
    assert asset.verified is True
    liability = _facade(accession).financials.level3_rollforward(
        axis_qname="us-gaap:FairValueByLiabilityClassAxis",
        member_qname="us-gaap:LongTermDebtMember",
    )
    assert liability.opening == 614_000_000.0
    assert liability.closing == 553_000_000.0
    assert liability.gains_earnings == 64_000_000.0
    assert liability.verified is True
    assert liability.graph.side == "liability"


def test_level3_rollforward_verifies_jpm_loans_by_components_and_change() -> None:
    """JPM loans verify by components and by the filed period net change."""
    view = _facade("0000019617-25-000270").financials.level3_rollforward(
        axis_qname="us-gaap:FairValueByAssetClassAxis",
        member_qname="jpm:LoansReceivableNotForTradingMember",
    )
    assert view.opening == 3_079_000_000.0
    assert view.closing == 2_416_000_000.0
    assert view.verified is True
    assert view.net_change == -663_000_000.0
    assert view.change_verified is True
    assert view.missing_components == ("issues",)


def test_level3_rollforward_reports_ms_gap_with_missing_component() -> None:
    """MS commodity derivatives fall short; the gap and missing role show."""
    view = _facade("0000895421-25-000304").financials.level3_rollforward(
        axis_qname="us-gaap:DerivativeInstrumentRiskAxis",
        member_qname="ms:CommodityAndOtherContractsMember",
    )
    assert view.opening == 1_290_000_000.0
    assert view.closing == 1_308_000_000.0
    assert view.verified is False
    assert view.discrepancy == -306_000_000.0
    assert "sales" in view.missing_components


_LOCATION_AXIS = "us-gaap:RetirementPlanSponsorLocationAxis"
_TYPE_AXIS = "us-gaap:RetirementPlanTypeAxis"


def test_pension_funded_status_verifies_ford_us_pension_class() -> None:
    """Ford US pension: both rollforwards and funded status verify."""
    view = _facade("0000037996-25-000013").financials.pension_funded_status(
        axis_qname=_LOCATION_AXIS, member_qname="country:US"
    )
    assert view.assets_opening == 31_423_000_000.0
    assert view.assets_closing == 29_502_000_000.0
    assert view.plan_assets.movements["actual_return"] == 13_000_000.0
    assert view.plan_assets.movements["employer_contributions"] == 808_000_000.0
    assert view.plan_assets.movements["benefits_paid"] == 2_706_000_000.0
    assert view.assets_verified is True
    assert view.obligation_opening == 32_676_000_000.0
    assert view.obligation_closing == 30_555_000_000.0
    assert view.obligation.movements["service_cost"] == 288_000_000.0
    assert view.obligation.movements["actuarial"] == 1_359_000_000.0
    assert view.obligation_verified is True
    assert view.funded_status == -1_053_000_000.0
    assert view.funded_status_filed == -1_053_000_000.0
    assert view.funded_verified is True
    assert view.missing_components == ()


def test_pension_funded_status_verifies_ford_foreign_and_opeb_classes() -> None:
    """Ford foreign pension and OPEB classes verify on all three checks."""
    foreign = _facade("0000037996-25-000013").financials.pension_funded_status(
        axis_qname=_LOCATION_AXIS, member_qname="us-gaap:ForeignPlanMember"
    )
    assert foreign.assets_opening == 22_958_000_000.0
    assert foreign.assets_closing == 21_751_000_000.0
    assert foreign.assets_verified is True
    assert foreign.obligation_opening == 24_004_000_000.0
    assert foreign.obligation_closing == 21_245_000_000.0
    assert foreign.obligation_verified is True
    assert foreign.funded_status == 506_000_000.0
    assert foreign.funded_verified is True
    opeb = _facade("0000037996-25-000013").financials.pension_funded_status(
        axis_qname=_TYPE_AXIS,
        member_qname="us-gaap:OtherPostretirementBenefitPlansDefinedBenefitMember",
    )
    assert opeb.assets_closing == 0.0
    assert opeb.obligation_opening == 4_696_000_000.0
    assert opeb.obligation_closing == 4_415_000_000.0
    assert opeb.obligation_verified is True
    assert opeb.funded_status == -4_415_000_000.0
    assert opeb.funded_verified is True


_EQ_AXIS = "us-gaap:StatementEquityComponentsAxis"
_RE_MEMBER = "us-gaap:RetainedEarningsMember"
_AOCI_MEMBER = "us-gaap:AccumulatedOtherComprehensiveIncomeMember"


def test_equity_rollforward_verifies_aapl_statement() -> None:
    """AAPL equity statement verifies per component and in total."""
    entry = _battery("aapl-segment-revenue-china")
    view = _facade(entry.accession).statements.equity_rollforward()
    assert view.axis_qname == _EQ_AXIS
    assert view.balance_concept == "us-gaap:StockholdersEquity"
    assert view.opening == 62_146_000_000.0
    assert view.closing == 56_950_000_000.0
    assert view.verified is True
    assert view.discrepancy == 0.0
    assert view.components_verified is True
    common = view.component("us-gaap:CommonStockIncludingAdditionalPaidInCapitalMember")
    assert common is not None
    assert common.opening == 73_812_000_000.0
    assert common.closing == 83_276_000_000.0
    assert common.movements["share_based_compensation"] == 12_034_000_000.0
    assert common.movements["issuance"] == 1_423_000_000.0
    assert common.movements["tax_withholding"] == -3_993_000_000.0
    assert common.verified is True
    retained = view.component(_RE_MEMBER)
    assert retained is not None
    assert retained.opening == -214_000_000.0
    assert retained.closing == -19_154_000_000.0
    assert retained.movements["net_income"] == 93_736_000_000.0
    assert retained.movements["dividends"] == -15_218_000_000.0
    assert retained.movements["repurchase"] == -95_846_000_000.0
    assert retained.verified is True
    aoci = view.component(_AOCI_MEMBER)
    assert aoci is not None
    assert aoci.opening == -11_452_000_000.0
    assert aoci.closing == -7_172_000_000.0
    assert aoci.movements["oci"] == 4_280_000_000.0
    assert aoci.verified is True
    assert set(view.antichain_members) == {
        "us-gaap:CommonStockIncludingAdditionalPaidInCapitalMember",
        _RE_MEMBER,
        _AOCI_MEMBER,
    }
    assert view.missing_components == ()


def test_equity_rollforward_verifies_msft_components_reports_common_gap() -> None:
    """MSFT retained earnings and AOCI verify; the common gap is reported."""
    view = _facade("0000950170-24-087843").statements.equity_rollforward()
    assert view.opening == 206_223_000_000.0
    assert view.closing == 268_477_000_000.0
    assert view.components_verified is True
    retained = view.component(_RE_MEMBER)
    assert retained is not None
    assert retained.opening == 118_848_000_000.0
    assert retained.closing == 173_144_000_000.0
    assert retained.movements["net_income"] == 88_136_000_000.0
    assert retained.movements["dividends"] == -22_293_000_000.0
    assert retained.movements["repurchase"] == -11_547_000_000.0
    assert retained.verified is True
    aoci = view.component(_AOCI_MEMBER)
    assert aoci is not None
    assert aoci.opening == -6_343_000_000.0
    assert aoci.closing == -5_590_000_000.0
    assert aoci.movements["oci"] == 753_000_000.0
    assert aoci.verified is True
    common = view.component("us-gaap:CommonStockIncludingAdditionalPaidInCapitalMember")
    assert common is not None
    assert common.verified is False
    assert common.discrepancy == 362_000_000.0
    assert view.verified is False
    assert view.discrepancy == 362_000_000.0


def test_equity_rollforward_verifies_jpm_components() -> None:
    """JPM APIC, preferred, treasury, and AOCI verify; retained gap shows."""
    view = _facade("0000019617-25-000270").statements.equity_rollforward()
    assert view.opening == 327_878_000_000.0
    assert view.closing == 344_758_000_000.0
    assert view.components_verified is True
    apic = view.component("us-gaap:AdditionalPaidInCapitalMember")
    assert apic is not None
    assert apic.opening == 90_128_000_000.0
    assert apic.closing == 90_911_000_000.0
    assert apic.movements["share_based_compensation"] == 768_000_000.0
    assert apic.movements["other"] == 15_000_000.0
    assert apic.verified is True
    preferred = view.component(
        "us-gaap:PreferredStockIncludingAdditionalPaidInCapitalMember"
    )
    assert preferred is not None
    assert preferred.opening == 27_404_000_000.0
    assert preferred.closing == 20_050_000_000.0
    assert preferred.movements["issuance"] == 2_496_000_000.0
    assert preferred.movements["repurchase"] == -9_850_000_000.0
    assert preferred.verified is True
    treasury = view.component("us-gaap:TreasuryStockCommonMember")
    assert treasury is not None
    assert treasury.opening == -116_217_000_000.0
    assert treasury.closing == -134_018_000_000.0
    assert treasury.movements["treasury_acquired"] == -19_007_000_000.0
    assert treasury.movements["treasury_reissued"] == 1_206_000_000.0
    assert treasury.verified is True
    common = view.component("us-gaap:CommonStockMember")
    assert common is not None
    assert common.movements == {}
    assert common.verified is True
    aoci = view.component(_AOCI_MEMBER)
    assert aoci is not None
    assert aoci.opening == -10_443_000_000.0
    assert aoci.closing == -12_456_000_000.0
    assert aoci.movements["oci"] == -2_013_000_000.0
    assert aoci.verified is True
    retained = view.component(_RE_MEMBER)
    assert retained is not None
    assert retained.verified is False
    assert retained.discrepancy == -161_000_000.0
    assert view.verified is False
    assert view.discrepancy == -161_000_000.0


def test_equity_rollforward_serves_cat_including_nci_total() -> None:
    """CAT's balance concept is the including-noncontrolling-interest total."""
    view = _facade("0000018230-25-000008").statements.equity_rollforward()
    assert (
        view.balance_concept
        == "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
    )
    assert view.opening == 19_503_000_000.0
    assert view.closing == 19_494_000_000.0
    assert view.components_verified is True
    retained = view.component(_RE_MEMBER)
    assert retained is not None
    assert retained.opening == 51_250_000_000.0
    assert retained.closing == 59_352_000_000.0
    assert retained.movements["net_income"] == 10_792_000_000.0
    assert retained.movements["dividends"] == -2_690_000_000.0
    assert retained.verified is True
    aoci = view.component(_AOCI_MEMBER)
    assert aoci is not None
    assert aoci.verified is False
    assert aoci.discrepancy == -24_000_000.0
    assert view.verified is False
    assert view.discrepancy == -28_000_000.0
    via_financials = _facade("0000018230-25-000008").financials.equity_rollforward()
    assert via_financials.closing == view.closing


def test_pension_funded_status_verifies_cat_us_pension_class() -> None:
    """CAT US pension verifies; its frozen plan files zero service cost."""
    view = _facade("0000018230-25-000008").financials.pension_funded_status(
        axis_qname=_LOCATION_AXIS, member_qname="country:US"
    )
    assert view.assets_opening == 12_738_000_000.0
    assert view.assets_closing == 11_898_000_000.0
    assert view.assets_verified is True
    assert view.obligation_opening == 13_137_000_000.0
    assert view.obligation_closing == 12_171_000_000.0
    assert view.obligation.movements["service_cost"] == 0.0
    assert view.obligation.movements["interest_cost"] == 625_000_000.0
    assert view.obligation_verified is True
    assert view.funded_status == -273_000_000.0
    assert view.funded_status_filed == -273_000_000.0
    assert view.funded_verified is True
