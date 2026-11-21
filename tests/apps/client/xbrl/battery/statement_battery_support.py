"""Shared battery fixtures and helpers for the statement audit suites."""

from __future__ import annotations

from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.discovery.cohort import load_canonical_union_cohort
from edgar_sec.engine.xbrl.review.battery import BATTERY_SET, BatteryEntry
from edgar_sec.engine.xbrl.schema.models import FilingXbrl, LinkbaseBundle
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


_NODE_EXCLUDED = _EPS | {
    # The cash rollup identity is presentational for JPM: the rollup
    # concept is no calculation child in any of the three statements.
    "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    # The balance-sheet identity total is a sibling root, never a
    # calculation descendant of the assets root.
    "us-gaap:LiabilitiesAndStockholdersEquity",
}


_SERIES_PINNED = {
    "wmt-revenue": 648_125_000_000.0,
    "duk-revenue-including-assessed-tax": 30_357_000_000.0,
    "bac-2013-revenue": 89_801_000_000.0,
    "bac-2019-revenue": 91_839_000_000.0,
    "bac-2021-revenue": 89_540_000_000.0,
    "bac-2023-revenue": 99_148_000_000.0,
}


_NODE_EXCLUDED_ENTRIES = {
    "bac-xva-derivative-assets",
    "bac-2015-cash",
    "asml-2024-cash",
}


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


_FACADES: dict[str, Xbrl] = {}


_GRAPHS: dict[tuple[str, str], dict[str, object]] = {}


_LOADED: dict[str, object] = {}


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


def _battery(entry_id: str) -> BatteryEntry:
    return next(e for e in BATTERY_SET if e.entry_id == entry_id)


_EPS_PINNED = {"xom-eps-diluted"}


_LOCATION_AXIS = "us-gaap:RetirementPlanSponsorLocationAxis"


_TYPE_AXIS = "us-gaap:RetirementPlanTypeAxis"


_EQ_AXIS = "us-gaap:StatementEquityComponentsAxis"


_RE_MEMBER = "us-gaap:RetainedEarningsMember"


_AOCI_MEMBER = "us-gaap:AccumulatedOtherComprehensiveIncomeMember"
