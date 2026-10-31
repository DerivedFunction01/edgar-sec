"""Tests proving ergonomic Layer 5 XBRL client facade, statements, and YoY math."""

import pytest

from edgar_sec.apps.client.comparison import panel_query
from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.schema.models import (
    ConceptLabel,
    FilingXbrl,
    LinkbaseBundle,
    XbrlFact,
)
from edgar_sec.engine.xbrl.solve.query import (
    FinancialQuery,
    FinancialQueryEngine,
    FinancialQueryResult,
    QueryMode,
    QueryStatus,
)
from edgar_sec.engine.xbrl.solve.scoping import FactScope
from edgar_sec.engine.xbrl.solve.solver import XbrlConstraintSolver
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.engine.xbrl.solve.conftest import (
    load_seed_calculation_arcs,
    load_seed_facts,
    seed_folder,
)

_MSFT_ACCESSION = "0000950170-24-087843"
_STANDARD_LABEL_ROLE = "http://www.xbrl.org/2003/role/label"
_TERSE_LABEL_ROLE = "http://www.xbrl.org/2003/role/terseLabel"


def _create_xbrl_facade(firm: str) -> Xbrl:
    facts = load_seed_facts(seed_folder(firm))
    arcs = load_seed_calculation_arcs(seed_folder(firm))
    bundle = FilingXbrl(
        accession=AccessionNumber("0000000000-24-000000"),
        cik=Cik(0),
        facts=facts,
        linkbases=LinkbaseBundle(calculation_arcs=arcs),
    )
    return Xbrl(bundle, load_domain_taxonomy())


def _create_labelled_xbrl_facade() -> Xbrl:
    facts = load_seed_facts("msft_2024_10k")
    arcs = load_seed_calculation_arcs("msft_2024_10k")
    labels = (
        ConceptLabel(
            concept_qname="us-gaap:Assets",
            role_uri=_STANDARD_LABEL_ROLE,
            label="Total Assets (Standard)",
            lang="en-US",
        ),
        ConceptLabel(
            concept_qname="us-gaap:Assets",
            role_uri=_TERSE_LABEL_ROLE,
            label="Terse Assets",
            lang="en-US",
        ),
        ConceptLabel(
            concept_qname="us-gaap:Assets",
            role_uri=_STANDARD_LABEL_ROLE,
            label="Actifs Totaux",
            lang="fr-FR",
        ),
        ConceptLabel(
            concept_qname="us-gaap:AssetsCurrent",
            role_uri=_TERSE_LABEL_ROLE,
            label="Current Assets (Terse)",
            lang="en-US",
        ),
    )
    bundle = FilingXbrl(
        accession=AccessionNumber("0000000000-24-000000"),
        cik=Cik(0),
        facts=facts,
        linkbases=LinkbaseBundle(calculation_arcs=arcs, labels=labels),
    )
    return Xbrl(bundle, load_domain_taxonomy())


def _oracle_query(
    term: str, scope: FactScope, mode: QueryMode = QueryMode.REPORTED_ONLY
) -> FinancialQueryResult:
    engine = FinancialQueryEngine(
        XbrlConstraintSolver(EvidenceKnowledgeBase(load_domain_taxonomy()))
    )
    return engine.execute(
        FinancialQuery(term, scope, mode=mode),
        load_seed_facts("msft_2024_10k"),
        load_seed_calculation_arcs("msft_2024_10k"),
    )


def test_xbrl_facade_facts_query() -> None:
    """Verify fluent fact query filtering, atom resolution, and tabular exports."""
    xbrl = _create_xbrl_facade("msft")

    assert len(xbrl.facts) > 1000
    rev_facts = xbrl.facts.query().atom("H_REVENUE").execute()
    assert len(rev_facts) > 0
    assert any("RevenueFromContractWithCustomer" in f.concept_qname for f in rev_facts)

    concept_facts = (
        xbrl.facts.query()
        .concept("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax")
        .execute()
    )
    assert len(concept_facts) > 0

    df = rev_facts.to_dataframe()
    assert len(df) == len(rev_facts)
    arrow_tbl = rev_facts.to_arrow()
    assert arrow_tbl.num_rows == len(rev_facts)


def test_xbrl_facade_statements_and_yoy() -> None:
    """Verify multi-year statement views, YoY series, and year filtering."""
    xbrl = _create_xbrl_facade("msft")

    stmt = xbrl.statements.income_statement()
    assert stmt.root is not None
    assert stmt.root.value == 88136000000.0
    assert "2024" in stmt.years
    assert "2023" in stmt.years

    rendered = stmt.render_ascii()
    assert "[INCOME STATEMENT:" in rendered
    assert "$88,136,000,000" in rendered
    assert "YoY:" in rendered

    df = stmt.to_dataframe(include_yoy=True)
    assert len(df) > 0

    stmt_2023 = xbrl.statements.income_statement(year=2023)
    assert stmt_2023.years == ("2023",)
    assert stmt_2023.root is not None
    assert stmt_2023.root.value == 72361000000.0

    bs = xbrl.statements.balance_sheet()
    assert bs.root is not None
    assert bs.root.value == 512163000000.0


def test_xbrl_financials_across_all_8_fixtures() -> None:
    """Prove dynamic subatomic financial metrics across all 8 ground fixtures."""
    firms = ("msft", "aapl", "jnj", "f", "jpm", "apd", "amzn", "dis")

    for firm in firms:
        xbrl = _create_xbrl_facade(firm)
        fin = xbrl.financials

        assert fin.revenue is not None and fin.revenue > 0
        assert fin.total_assets is not None and fin.total_assets > 0
        assert fin.net_income is not None

        rev_series = fin.revenue_series
        assert len(rev_series) >= 2
        rev_yoy = fin.revenue_yoy
        assert rev_yoy is not None
        assert isinstance(rev_yoy[0], float)

        derivatives = fin.derivatives
        assert derivatives is not None
        d_df = derivatives.to_dataframe()
        assert d_df is not None
        d_ascii = derivatives.render_ascii()
        assert "[DERIVATIVE PORTFOLIO EXPOSURE]" in d_ascii

        debt = fin.debt
        assert debt is not None
        debt_df = debt.to_dataframe()
        assert debt_df is not None
        debt_ascii = debt.render_ascii()
        assert "[DEBT AND CAPITAL STRUCTURE]" in debt_ascii


def test_xbrl_chain_and_graph() -> None:
    """Verify topological rollup chains and arbitrary root graph builds."""
    xbrl = _create_xbrl_facade("msft")

    chain = xbrl.chain(
        child_concept="us-gaap:CostOfGoodsAndServicesSold",
        root_concept="us-gaap:GrossProfit",
    )
    assert len(chain) == 2
    assert chain[0].concept_qname == "us-gaap:CostOfGoodsAndServicesSold"
    assert chain[1].concept_qname == "us-gaap:GrossProfit"

    custom_graph = xbrl.graph("us-gaap:Assets")
    assert custom_graph.root is not None
    assert custom_graph.root.value == 512163000000.0


def test_xbrl_statement_table_and_comparison() -> None:
    """Verify clean accounting table formatting and multi-firm comparison."""
    msft = _create_xbrl_facade("msft")
    aapl = _create_xbrl_facade("aapl")
    jpm = _create_xbrl_facade("jpm")

    inc = aapl.statements.income_statement()
    table_str = inc.render_table()
    assert "[INCOME STATEMENT]" in table_str
    assert "FY 2024" in table_str
    assert "FY 2023" in table_str
    assert "YoY (%)" in table_str
    assert "$391,035,000,000" in table_str
    assert "$93,736,000,000" in table_str
    assert "(+)" not in table_str
    assert str(inc) == table_str

    comp_view = msft.compare([aapl, jpm])
    c_table = comp_view.render_table()
    assert "Revenue" in c_table
    assert "Operating Margin" in c_table
    assert "Net Margin" in c_table
    assert "Return on Assets (ROA)" in c_table

    c_df = comp_view.to_dataframe()
    assert len(c_df) > 0


def test_xbrl_macro_commitments_and_cash_flow() -> None:
    """Verify ASC 606 RPO backlog, Capex, and Free Cash Flow derivation."""
    msft = _create_xbrl_facade("msft")
    aapl = _create_xbrl_facade("aapl")

    assert msft.financials.rpo == 275_000_000_000.0
    assert msft.financials.capex == 44_477_000_000.0
    assert msft.financials.free_cash_flow == 74_071_000_000.0
    assert "2024" in msft.financials.capex_series

    assert aapl.financials.rpo is None
    assert aapl.financials.capex == 9_447_000_000.0
    assert aapl.financials.free_cash_flow == 108_807_000_000.0


def test_xbrl_facade_with_labels_uses_standard_en_us_label() -> None:
    """Verify labelled bundles construct and standard en-US labels win."""
    xbrl = _create_labelled_xbrl_facade()

    view = xbrl.graph("us-gaap:Assets")
    assert view.root is not None
    assert view.root.label == "Total Assets (Standard)"
    assert view.nodes["us-gaap:AssetsCurrent"].label == "Current Assets (Terse)"

    balance_sheet = xbrl.statements.balance_sheet()
    assert balance_sheet.root is not None
    assert balance_sheet.root.label == "Total Assets (Standard)"


def test_xbrl_query_reported_duration_with_fiscal_year() -> None:
    """Verify fiscal-year duration queries match the engine oracle."""
    xbrl = _create_xbrl_facade("msft")
    oracle = _oracle_query(
        "Net Income",
        FactScope(
            accession=_MSFT_ACCESSION,
            start_date="2023-07-01",
            end_date="2024-06-30",
            unit="USD",
        ),
    )

    for term in ("Net Income", "us-gaap:NetIncomeLoss"):
        result = xbrl.query(term, fiscal_year=2024)
        assert result.status == QueryStatus.REPORTED
        assert result.value == oracle.value == 88136000000.0


def test_xbrl_query_reported_instant_with_fiscal_year() -> None:
    """Verify fiscal-year instant queries match the engine oracle."""
    xbrl = _create_xbrl_facade("msft")
    oracle = _oracle_query(
        "us-gaap:Assets",
        FactScope(accession=_MSFT_ACCESSION, instant_date="2024-06-30", unit="USD"),
    )

    result = xbrl.query("us-gaap:Assets", fiscal_year=2024)
    assert result.status == QueryStatus.REPORTED
    assert result.value == oracle.value == 512163000000.0


def test_xbrl_query_without_fiscal_year_is_ambiguous() -> None:
    """Verify a multi-context concept without a year stays ambiguous."""
    xbrl = _create_xbrl_facade("msft")

    result = xbrl.query("us-gaap:Assets")
    assert result.status == QueryStatus.AMBIGUOUS
    assert result.value is None


def test_xbrl_query_verify_derivation_matches_oracle() -> None:
    """Verify VERIFY_DERIVATION reconciles against the engine oracle."""
    xbrl = _create_xbrl_facade("msft")
    scope = FactScope(
        accession=_MSFT_ACCESSION,
        start_date="2023-07-01",
        end_date="2024-06-30",
        unit="USD",
    )
    oracle = _oracle_query("Net Income", scope, mode=QueryMode.VERIFY_DERIVATION)

    for mode in ("VERIFY_DERIVATION", QueryMode.VERIFY_DERIVATION):
        result = xbrl.query("Net Income", mode=mode, fiscal_year=2024)
        assert result.status == oracle.status == QueryStatus.VERIFIED
        assert result.value == oracle.value
        assert result.discrepancy == oracle.discrepancy == 0.0


def test_xbrl_query_invalid_mode_raises() -> None:
    """Verify unknown query modes raise instead of silently coercing."""
    xbrl = _create_xbrl_facade("msft")

    for bad_mode in ("SOLVED_FALLBACK", "bogus"):
        with pytest.raises(ValueError):
            xbrl.query("Net Income", mode=bad_mode, fiscal_year=2024)


def test_xbrl_query_explicit_scope_passthrough() -> None:
    """Verify an explicit scope is executed verbatim."""
    xbrl = _create_xbrl_facade("msft")
    scope = FactScope(accession=_MSFT_ACCESSION, instant_date="2024-06-30", unit="USD")
    oracle = _oracle_query("us-gaap:Assets", scope)

    result = xbrl.query("us-gaap:Assets", scope=scope)
    assert result.status == oracle.status == QueryStatus.REPORTED
    assert result.value == oracle.value


def test_xbrl_query_unknown_term_with_fiscal_year() -> None:
    """Verify unknown terms return UNAVAILABLE instead of raising."""
    xbrl = _create_xbrl_facade("msft")

    result = xbrl.query("UnrecognizedFinancialMeasure", fiscal_year=2024)
    assert result.status == QueryStatus.UNAVAILABLE
    assert result.value is None


_SYNTHETIC_ACCESSION = "0000000001-23-000001"
_ANNUAL = ("2023-01-01", "2023-12-31")


def _synthetic_fact(
    qname: str,
    value: float,
    start: str | None = None,
    end: str | None = None,
    instant: str | None = None,
) -> XbrlFact:
    return XbrlFact(
        accession=AccessionNumber(_SYNTHETIC_ACCESSION),
        concept_qname=qname,
        value=value,
        unit="USD",
        period_type="instant" if instant is not None else "duration",
        start_date=start,
        end_date=end,
        instant_date=instant,
    )


def _create_synthetic_xbrl(facts: tuple[XbrlFact, ...]) -> Xbrl:
    bundle = FilingXbrl(
        accession=AccessionNumber("0000000000-24-000000"),
        cik=Cik(0),
        facts=facts,
        linkbases=LinkbaseBundle(),
    )
    return Xbrl(bundle, load_domain_taxonomy())


def test_xbrl_query_fiscal_year_annual_conflict_beats_quarterly_reported() -> None:
    """Verify a quarterly REPORTED never outranks the annual tier's CONFLICT."""
    xbrl = _create_synthetic_xbrl(
        (
            _synthetic_fact(
                "us-gaap:Revenues", 100.0, start=_ANNUAL[0], end=_ANNUAL[1]
            ),
            _synthetic_fact(
                "us-gaap:Revenues", 150.0, start=_ANNUAL[0], end=_ANNUAL[1]
            ),
            _synthetic_fact(
                "us-gaap:Revenues", 30.0, start="2023-07-01", end="2023-09-30"
            ),
        )
    )

    result = xbrl.query("revenue", fiscal_year=2023)
    assert result.status == QueryStatus.CONFLICT
    assert result.value is None


_TIMING_AXIS = (
    "us-gaap:RevenueRemainingPerformanceObligation"
    "ExpectedTimingOfSatisfactionStartDateAxis"
)
_RPO_CONCEPT = "us-gaap:RevenueRemainingPerformanceObligation"


def _timed_rpo(value: float, member: str) -> XbrlFact:
    return XbrlFact(
        accession=AccessionNumber(_SYNTHETIC_ACCESSION),
        concept_qname=_RPO_CONCEPT,
        value=value,
        unit="USD",
        period_type="instant",
        instant_date="2023-12-31",
        dimensions={_TIMING_AXIS: member},
    )


def test_xbrl_query_dimension_policy_answers_total_on_timing_axis() -> None:
    """Verify the horizon-totals policy answers a total filed only on a timing axis."""
    xbrl = _create_synthetic_xbrl(
        (
            _synthetic_fact("us-gaap:Assets", 999.0, instant="2023-12-31"),
            _timed_rpo(155.7, "2024-01-01"),
        )
    )

    default = xbrl.query(_RPO_CONCEPT, fiscal_year=2023)
    assert default.status == QueryStatus.UNAVAILABLE
    assert default.value is None

    opted = xbrl.query(
        _RPO_CONCEPT, fiscal_year=2023, dimension_policy="horizon_totals"
    )
    assert opted.status == QueryStatus.REPORTED
    assert opted.value == 155.7


def test_xbrl_query_dimension_policy_keeps_undimensioned_total() -> None:
    """Verify an undimensioned total outranks a dimensioned one under the policy."""
    xbrl = _create_synthetic_xbrl(
        (
            _synthetic_fact(_RPO_CONCEPT, 100.0, instant="2023-12-31"),
            _timed_rpo(150.0, "2024-01-01"),
        )
    )

    result = xbrl.query(
        _RPO_CONCEPT, fiscal_year=2023, dimension_policy="horizon_totals"
    )
    assert result.status == QueryStatus.REPORTED
    assert result.value == 100.0


def test_xbrl_query_dimension_policy_multiple_members_is_ambiguous() -> None:
    """Verify totals filed on several timing members are AMBIGUOUS, not a pick."""
    xbrl = _create_synthetic_xbrl(
        (
            _synthetic_fact("us-gaap:Assets", 999.0, instant="2023-12-31"),
            _timed_rpo(100.0, "2024-01-01"),
            _timed_rpo(150.0, "2025-01-01"),
        )
    )

    result = xbrl.query(
        _RPO_CONCEPT, fiscal_year=2023, dimension_policy="horizon_totals"
    )
    assert result.status == QueryStatus.AMBIGUOUS
    assert result.value is None


def test_xbrl_query_dimension_policy_amzn_specimen() -> None:
    """Verify Amazon's timing-axis RPO total answers only under the policy."""
    amzn = _create_xbrl_facade("amzn")

    default = amzn.query(_RPO_CONCEPT, fiscal_year=2023)
    assert default.status == QueryStatus.UNAVAILABLE

    opted = amzn.query(
        _RPO_CONCEPT, fiscal_year=2023, dimension_policy="horizon_totals"
    )
    assert opted.status == QueryStatus.REPORTED
    assert opted.value == 155_700_000_000.0

    msft = _create_xbrl_facade("msft")
    kept = msft.query(_RPO_CONCEPT, fiscal_year=2024, dimension_policy="horizon_totals")
    assert kept.status == QueryStatus.REPORTED
    assert kept.value == 275_000_000_000.0


def test_panel_query_fixed_year_all_answered() -> None:
    """Verify a fixed-year RPO panel answers every filer with a summed total."""
    facades = {firm: _create_xbrl_facade(firm) for firm in ("msft", "googl", "orcl")}
    panel = panel_query(facades, _RPO_CONCEPT, fiscal_year=2024)
    assert panel.missing == ()
    assert [row.value for row in panel.rows] == [
        275_000_000_000.0,
        93_200_000_000.0,
        97_900_000_000.0,
    ]
    assert panel.total == 466_100_000_000.0


def test_panel_query_latest_per_filer_with_policy() -> None:
    """Verify a latest-filings panel mixes vintages and answers Amazon's total."""
    facades = {
        firm: _create_xbrl_facade(firm) for firm in ("msft", "amzn", "googl", "orcl")
    }
    panel = panel_query(facades, _RPO_CONCEPT, dimension_policy="horizon_totals")
    assert panel.missing == ()
    values = {row.filer: row.value for row in panel.rows}
    assert values["amzn"] == 155_700_000_000.0
    assert panel.total == 621_800_000_000.0

    default = panel_query(facades, _RPO_CONCEPT)
    assert default.missing == ("amzn",)
    assert default.total == 466_100_000_000.0


def test_panel_query_names_unanswered_filers() -> None:
    """Verify a filer with no RPO fact is an explicit missing row, not a drop."""
    facades = {firm: _create_xbrl_facade(firm) for firm in ("msft", "aapl")}
    panel = panel_query(facades, _RPO_CONCEPT, dimension_policy="horizon_totals")
    assert panel.missing == ("aapl",)
    aapl_row = next(row for row in panel.rows if row.filer == "aapl")
    assert aapl_row.status == QueryStatus.UNAVAILABLE
    assert aapl_row.value is None


def test_compose_dimension_policy_propagates_to_operands() -> None:
    """Verify composed chains value Amazon's backlog only under the policy."""
    amzn = _create_xbrl_facade("amzn")
    terms = [("+", _RPO_CONCEPT), ("+", "us-gaap:ContractWithCustomerLiability")]

    default = amzn.compose(terms, fiscal_year=2023)
    assert default.value is None

    opted = amzn.compose(terms, fiscal_year=2023, dimension_policy="horizon_totals")
    assert opted.status == QueryStatus.REPORTED
    assert opted.value == 176_300_000_000.0


def test_xbrl_query_unknown_dimension_policy_raises() -> None:
    """Verify an unknown dimension policy string raises ValueError."""
    xbrl = _create_xbrl_facade("msft")
    with pytest.raises(ValueError, match="dimension policy"):
        xbrl.query("revenue", fiscal_year=2024, dimension_policy="everything")


def test_xbrl_query_fiscal_year_quarterly_only_concept_is_unavailable() -> None:
    """Verify a non-annual-only concept is UNAVAILABLE for a fiscal-year query."""
    xbrl = _create_synthetic_xbrl(
        (
            _synthetic_fact(
                "us-gaap:Revenues", 100.0, start=_ANNUAL[0], end=_ANNUAL[1]
            ),
            _synthetic_fact("us-gaap:Assets", 500.0, instant="2023-12-31"),
            _synthetic_fact(
                "us-gaap:GrossProfit", 40.0, start="2023-07-01", end="2023-09-30"
            ),
            _synthetic_fact(
                "us-gaap:GrossProfit", 35.0, start="2023-04-01", end="2023-06-30"
            ),
        )
    )

    result = xbrl.query("us-gaap:GrossProfit", fiscal_year=2023)
    assert result.status == QueryStatus.UNAVAILABLE
    assert result.value is None


def test_xbrl_query_length_class_selects_its_own_span() -> None:
    """Verify QUARTER and YTD_2Q requests answer from their own spans."""
    xbrl = _create_synthetic_xbrl(
        (
            _synthetic_fact(
                "us-gaap:Revenues", 100.0, start=_ANNUAL[0], end=_ANNUAL[1]
            ),
            _synthetic_fact(
                "us-gaap:Revenues", 30.0, start="2023-07-01", end="2023-09-30"
            ),
            _synthetic_fact(
                "us-gaap:Revenues", 55.0, start="2023-01-01", end="2023-06-30"
            ),
            _synthetic_fact("us-gaap:Assets", 500.0, instant="2023-12-31"),
        )
    )

    annual = xbrl.query("us-gaap:Revenues", fiscal_year=2023)
    assert annual.status == QueryStatus.REPORTED
    assert annual.value == 100.0
    quarter = xbrl.query("us-gaap:Revenues", fiscal_year=2023, length_class="QUARTER")
    assert quarter.status == QueryStatus.REPORTED
    assert quarter.value == 30.0
    ytd = xbrl.query("us-gaap:Revenues", fiscal_year=2023, length_class="YTD_2Q")
    assert ytd.status == QueryStatus.REPORTED
    assert ytd.value == 55.0
    instant = xbrl.query("us-gaap:Assets", fiscal_year=2023, length_class="INSTANT")
    assert instant.status == QueryStatus.REPORTED
    assert instant.value == 500.0


def test_xbrl_query_length_class_without_matching_span_is_unavailable() -> None:
    """Verify a length class the filing does not carry stays UNAVAILABLE."""
    xbrl = _create_synthetic_xbrl(
        (
            _synthetic_fact(
                "us-gaap:Revenues", 100.0, start=_ANNUAL[0], end=_ANNUAL[1]
            ),
            _synthetic_fact(
                "us-gaap:Revenues", 30.0, start="2023-07-01", end="2023-09-30"
            ),
        )
    )

    result = xbrl.query("us-gaap:Revenues", fiscal_year=2023, length_class="YTD_3Q")
    assert result.status == QueryStatus.UNAVAILABLE
    assert result.value is None
    instant = xbrl.query("us-gaap:Revenues", fiscal_year=2023, length_class="INSTANT")
    assert instant.status == QueryStatus.UNAVAILABLE
    assert instant.value is None


def test_xbrl_query_fiscal_year_instant_fact_cannot_answer_duration_term() -> None:
    """Verify an instant-scope REPORTED (RPO) does not override the annual tier."""
    xbrl = _create_synthetic_xbrl(
        (
            _synthetic_fact(
                "us-gaap:Revenues", 100.0, start=_ANNUAL[0], end=_ANNUAL[1]
            ),
            _synthetic_fact(
                "us-gaap:Revenues", 150.0, start=_ANNUAL[0], end=_ANNUAL[1]
            ),
            _synthetic_fact(
                "us-gaap:RevenueRemainingPerformanceObligation",
                999.0,
                instant="2023-12-31",
            ),
        )
    )

    result = xbrl.query("revenue", fiscal_year=2023)
    assert result.status == QueryStatus.CONFLICT
    assert result.value is None


def test_xbrl_query_pld_revenue_fiscal_year_reports_annual_headline() -> None:
    """Verify PLD loose revenue returns the annual headline, not the Q3 REPORTED."""
    xbrl = _create_xbrl_facade("pld")

    result = xbrl.query("revenue", fiscal_year=2024)
    assert result.status == QueryStatus.REPORTED
    assert result.value == 8201610000.0


def test_xbrl_query_msft_revenue_fiscal_year_ignores_rpo_instants() -> None:
    """Verify MSFT loose revenue is AMBIGUOUS in both modes, never the RPO facts."""
    xbrl = _create_xbrl_facade("msft")

    for mode in (QueryMode.REPORTED_ONLY, QueryMode.VERIFY_DERIVATION):
        result = xbrl.query("revenue", mode=mode, fiscal_year=2024)
        assert result.status == QueryStatus.AMBIGUOUS
        assert result.value is None


def test_xbrl_query_nvda_revenue_verify_surfaces_annual_conflict() -> None:
    """Verify NVDA revenue VERIFY surfaces the annual tier's CONFLICT (G-pin).

    The RPO percentage never answers; the derivation does not reconcile.
    """
    xbrl = _create_xbrl_facade("nvda")

    result = xbrl.query("revenue", mode=QueryMode.VERIFY_DERIVATION, fiscal_year=2024)
    assert result.status == QueryStatus.CONFLICT
    assert result.reported_fact is not None
    assert result.reported_fact.value == 60922000000.0
    assert result.aggregate is not None
    assert result.aggregate.value == 44301000000.0
    assert result.value == 44301000000.0


def test_xbrl_query_aapl_assets_verify_resolves_at_fye_instant() -> None:
    """Verify AAPL Assets VERIFY returns the FYE VERIFIED, not a note-date DERIVED."""
    xbrl = _create_xbrl_facade("aapl")

    result = xbrl.query(
        "us-gaap:Assets", mode=QueryMode.VERIFY_DERIVATION, fiscal_year=2024
    )
    assert result.status == QueryStatus.VERIFIED
    assert result.value == 364980000000.0


def test_xbrl_query_aapl_derivative_assets_supertype_not_promoted() -> None:
    """Verify AAPL Derivative Assets is AMBIGUOUS: total Assets must not answer it."""
    xbrl = _create_xbrl_facade("aapl")

    for mode in (QueryMode.REPORTED_ONLY, QueryMode.VERIFY_DERIVATION):
        result = xbrl.query("Derivative Assets", mode=mode, fiscal_year=2024)
        assert result.status == QueryStatus.AMBIGUOUS
        assert result.value is None
        assert result.candidate_qnames == ("us-gaap:Assets",)
        assert result.tier == "near"
        assert len(result.equivalents) == 1
        assert result.equivalents[0].direction == "generalization"


def test_xbrl_query_aapl_derivative_liabilities_stays_ambiguous() -> None:
    """Verify AAPL Derivative Liabilities stays AMBIGUOUS over its equivalents."""
    xbrl = _create_xbrl_facade("aapl")

    result = xbrl.query("Derivative Liabilities", fiscal_year=2024)
    assert result.status == QueryStatus.AMBIGUOUS
    assert result.value is None
    assert len(result.candidate_qnames) == 7
    assert len(result.equivalents) == 7


def test_xbrl_query_gis_cash_verify_surfaces_fye_conflict() -> None:
    """Verify GIS Cash VERIFY surfaces the FYE tier's CONFLICT (G-pin).

    The unitless scope's AMBIGUOUS no longer shadows the USD derivation.
    """
    xbrl = _create_xbrl_facade("gis")

    result = xbrl.query(
        "us-gaap:CashAndCashEquivalentsAtCarryingValue",
        mode=QueryMode.VERIFY_DERIVATION,
        fiscal_year=2024,
    )
    assert result.status == QueryStatus.CONFLICT
    assert result.reported_fact is not None
    assert result.reported_fact.value == 418000000.0
    assert result.aggregate is not None
    assert result.aggregate.value == -6979900000.0
    assert result.value == -6979900000.0


def test_xbrl_query_gis_gross_profit_fiscal_year_unavailable() -> None:
    """Verify GIS's quarterly-only GrossProfit is UNAVAILABLE for a fiscal-year query."""
    xbrl = _create_xbrl_facade("gis")

    result = xbrl.query("us-gaap:GrossProfit", fiscal_year=2024)
    assert result.status == QueryStatus.UNAVAILABLE
    assert result.value is None


def test_xbrl_query_bac_cash_verify_resolves_at_fye_instant() -> None:
    """Verify BAC Cash VERIFY selects the FYE instant; its DERIVED there is a known solver limit."""
    xbrl = _create_xbrl_facade("bac")

    result = xbrl.query(
        "us-gaap:CashAndCashEquivalentsAtCarryingValue",
        mode=QueryMode.VERIFY_DERIVATION,
        fiscal_year=2024,
    )
    assert result.status == QueryStatus.DERIVED
    assert result.value == -558677000000.0


def test_xbrl_query_msft_eps_diluted_resolves_at_annual_scope() -> None:
    """Verify diluted EPS still resolves REPORTED at the annual unitless scope."""
    xbrl = _create_xbrl_facade("msft")
    annual = xbrl.query(
        "us-gaap:EarningsPerShareDiluted",
        scope=FactScope(
            accession=_MSFT_ACCESSION, start_date="2023-07-01", end_date="2024-06-30"
        ),
    )

    result = xbrl.query("us-gaap:EarningsPerShareDiluted", fiscal_year=2024)
    assert result.status == QueryStatus.REPORTED
    assert result.value == annual.value == 11.8


def _canned_result(status: QueryStatus, scope: FactScope) -> FinancialQueryResult:
    return FinancialQueryResult(FinancialQuery("term", scope), status)


@pytest.mark.parametrize(
    ("first_status", "second_status", "winner"),
    [
        (QueryStatus.CONFLICT, QueryStatus.VERIFIED, QueryStatus.VERIFIED),
        (QueryStatus.VERIFIED, QueryStatus.CONFLICT, QueryStatus.VERIFIED),
        (QueryStatus.CONFLICT, QueryStatus.REPORTED, QueryStatus.REPORTED),
        (QueryStatus.REPORTED, QueryStatus.CONFLICT, QueryStatus.REPORTED),
        (QueryStatus.DERIVED, QueryStatus.CONFLICT, QueryStatus.CONFLICT),
        (QueryStatus.CONFLICT, QueryStatus.DERIVED, QueryStatus.CONFLICT),
        (QueryStatus.AMBIGUOUS, QueryStatus.DERIVED, QueryStatus.DERIVED),
        (QueryStatus.DERIVED, QueryStatus.AMBIGUOUS, QueryStatus.DERIVED),
        (QueryStatus.AMBIGUOUS, QueryStatus.CONFLICT, QueryStatus.CONFLICT),
        (QueryStatus.CONFLICT, QueryStatus.AMBIGUOUS, QueryStatus.CONFLICT),
        (QueryStatus.UNAVAILABLE, QueryStatus.AMBIGUOUS, QueryStatus.AMBIGUOUS),
        (QueryStatus.AMBIGUOUS, QueryStatus.UNAVAILABLE, QueryStatus.AMBIGUOUS),
    ],
)
def test_tier_outcome_split_precedence_orders_statuses(
    monkeypatch: pytest.MonkeyPatch,
    first_status: QueryStatus,
    second_status: QueryStatus,
    winner: QueryStatus,
) -> None:
    """Verify the split precedence picks the higher status in either scope order."""
    xbrl = _create_synthetic_xbrl(
        (_synthetic_fact("us-gaap:Assets", 1.0, instant="2023-12-31"),)
    )
    scopes = (
        FactScope(accession=_SYNTHETIC_ACCESSION, instant_date="2023-12-31"),
        FactScope(
            accession=_SYNTHETIC_ACCESSION, instant_date="2023-12-31", unit="USD"
        ),
    )
    canned = {None: first_status, "USD": second_status}
    monkeypatch.setattr(
        xbrl._fiscal,
        "_execute_query",
        lambda term, mode, scope, arcs: _canned_result(canned[scope.unit], scope),
    )

    outcome, _, _ = xbrl._fiscal._tier_outcome(
        "term", QueryMode.REPORTED_ONLY, scopes, ()
    )
    assert outcome is not None
    assert outcome.status == winner


def test_tier_outcome_all_unavailable_returns_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify a silent tier returns its first scope's result, not a later one."""
    xbrl = _create_synthetic_xbrl(
        (_synthetic_fact("us-gaap:Assets", 1.0, instant="2023-12-31"),)
    )
    scopes = (
        FactScope(accession=_SYNTHETIC_ACCESSION, instant_date="2023-12-31"),
        FactScope(
            accession=_SYNTHETIC_ACCESSION, instant_date="2023-12-31", unit="USD"
        ),
    )
    canned = [_canned_result(QueryStatus.UNAVAILABLE, scope) for scope in scopes]
    by_unit = {scope.unit: result for scope, result in zip(scopes, canned)}
    monkeypatch.setattr(
        xbrl._fiscal,
        "_execute_query",
        lambda term, mode, scope, arcs: by_unit[scope.unit],
    )

    outcome, first, _ = xbrl._fiscal._tier_outcome(
        "term", QueryMode.REPORTED_ONLY, scopes, ()
    )
    assert outcome is canned[0]
    assert first is canned[0]


def test_xbrl_query_bac_net_income_verify_surfaces_usd_conflict() -> None:
    """Verify BAC Net Income VERIFY surfaces the USD CONFLICT over the AMBIGUOUS (G-pin)."""
    xbrl = _create_xbrl_facade("bac")

    result = xbrl.query(
        "us-gaap:NetIncomeLoss", mode=QueryMode.VERIFY_DERIVATION, fiscal_year=2024
    )
    assert result.status == QueryStatus.CONFLICT
    assert result.reported_fact is not None
    assert result.reported_fact.value == 27132000000.0
    assert result.aggregate is not None
    assert result.aggregate.value == 146607000000.0


def test_xbrl_query_gis_revenue_exact_carries_asc606_neighbour() -> None:
    """Verify GIS loose revenue is REPORTED exact with the ASC-606 neighbour visible (Q-B)."""
    xbrl = _create_xbrl_facade("gis")

    result = xbrl.query("revenue", fiscal_year=2024)
    assert result.status == QueryStatus.REPORTED
    assert result.value == 2037800000.0
    assert result.candidate_qnames == ("us-gaap:Revenues",)
    assert result.tier == "exact"
    by_qname = {item.qname: item for item in result.equivalents}
    assert by_qname["us-gaap:Revenues"].rule == "equality"
    neighbour = by_qname["us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"]
    assert neighbour.tier == "near"
    assert neighbour.rule == "subsumption"
    assert neighbour.direction == "specialization"


def test_xbrl_query_msft_revenue_rank_alone_never_promotes() -> None:
    """Verify MSFT revenue stays AMBIGUOUS: rank alone never promotes it (Q3(a))."""
    xbrl = _create_xbrl_facade("msft")

    for mode in (QueryMode.REPORTED_ONLY, QueryMode.VERIFY_DERIVATION):
        result = xbrl.query("revenue", mode=mode, fiscal_year=2024)
        assert result.status == QueryStatus.AMBIGUOUS
        assert result.value is None
        assert result.tier == "near"
        best = result.equivalents[0]
        assert best.qname == (
            "msft:ContractWithCustomerLiabilityRevenueRecognizedIncludingAdditions"
        )
        assert best.rule == "single_modifier_difference"
        assert best.direction == "specialization"


def test_xbrl_query_jnj_revenue_guard_promotion_surfaces_at_near_tier() -> None:
    """Verify JNJ revenue's guard promotion returns the headline, marked NEAR tier."""
    xbrl = _create_xbrl_facade("jnj")

    result = xbrl.query("revenue", fiscal_year=2024)
    assert result.status == QueryStatus.REPORTED
    assert result.value == 88821000000.0
    assert result.candidate_qnames == (
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    )
    assert result.tier == "near"
    assert result.equivalents[0].direction == "specialization"
