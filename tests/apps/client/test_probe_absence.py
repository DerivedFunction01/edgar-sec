"""Probe 8-K specimens: dei-only filings get honest absence, not shells."""

from __future__ import annotations

import pyarrow.parquet as pq
import pytest

from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.discovery.cohort import canonical_probe_cohort_path
from edgar_sec.engine.xbrl.schema.models import FilingXbrl, LinkbaseBundle
from edgar_sec.engine.xbrl.solve.query import QueryStatus
from edgar_sec.engine.xbrl.storage.storage import presentation_arcs_from_arrow_table
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.pipelines.xbrl_review.bundles import load_filing, registry_filings
from tests.engine.xbrl.solve.conftest import (
    load_seed_calculation_arcs,
    load_seed_facts,
)
from tests.support import bundle_dir

_FACADES: dict[str, Xbrl] = {}

_MSFT_8K = "0001193125-26-436122"
_AAPL_8K = "0000320193-26-000018"
_AMZN_8K = "0001018724-26-000024"
_AAPL_502 = "0001140361-26-015711"
_RECAST = "0001193125-26-436149"
_YYAI_8KA = "0001493152-26-017959"
_DEI_ONLY = (_MSFT_8K, _AAPL_8K, _AMZN_8K, _AAPL_502)
_FACTORIES = (
    "income_statement",
    "balance_sheet",
    "cash_flow_statement",
    "comprehensive_income_statement",
)


def _facade(accession: str) -> Xbrl:
    if accession not in _FACADES:
        seed = next(
            s
            for s in registry_filings(registry_path=canonical_probe_cohort_path())
            if str(s.accession) == accession
        )
        loaded = load_filing(seed, registry_path=canonical_probe_cohort_path())
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


def _seed_facade(folder: str, *, presentation: bool = True) -> Xbrl:
    pres_arcs = ()
    if presentation:
        table = pq.read_table(bundle_dir(folder) / "presentation_arcs.parquet")
        pres_arcs = presentation_arcs_from_arrow_table(table)
    bundle = FilingXbrl(
        accession=AccessionNumber("0000000000-24-000000"),
        cik=Cik(0),
        facts=load_seed_facts(folder),
        linkbases=LinkbaseBundle(
            calculation_arcs=load_seed_calculation_arcs(folder),
            presentation_arcs=pres_arcs,
        ),
    )
    return Xbrl(bundle, load_domain_taxonomy())


@pytest.mark.parametrize("accession", _DEI_ONLY)
@pytest.mark.parametrize("factory", _FACTORIES)
def test_dei_only_statement_factories_report_unavailable(
    accession: str, factory: str
) -> None:
    """Every algebraic factory signals UNAVAILABLE instead of a shell."""
    view = getattr(_facade(accession).statements, factory)()
    assert view.status is QueryStatus.UNAVAILABLE
    assert view.message
    assert view.root is None
    assert view.nodes == {}
    assert view.years == ()
    assert "(unreported)" not in view.render_ascii()
    assert "(unreported)" not in view.render_table()
    assert len(view.to_dataframe()) == 0


@pytest.mark.parametrize("accession", _DEI_ONLY)
def test_dei_only_topic_views_keep_none_posture(accession: str) -> None:
    """Topic views already report absence as None fields and zero rows."""
    statements = _facade(accession).statements
    assert statements.derivatives().gross_assets is None
    assert len(statements.derivatives().graph.positions) == 0
    assert statements.debt().total_debt is None
    assert statements.fair_value_hierarchy().rows == ()
    assert statements.equity_rollforward().closing is None
    assert statements.cash_rollforward().end is None


@pytest.mark.parametrize("accession", _DEI_ONLY)
def test_dei_only_presentation_path_serves_cover_only(accession: str) -> None:
    """The cover role serves its filed rows; statement roles do not exist."""
    statements = _facade(accession).statements
    assert statements.by_category("statement") == ()
    (cover_entry,) = statements.by_category("document")
    cover = statements.view(cover_entry.role_uri)
    assert len(cover.rows) > 0
    with pytest.raises(ValueError, match="no presentation role"):
        statements.view("Income Statement")


@pytest.mark.parametrize("accession", (_RECAST, _YYAI_8KA))
@pytest.mark.parametrize(
    "factory",
    ("income_statement", "balance_sheet", "cash_flow_statement"),
)
def test_statement_carrying_8k_factories_serve_statements(
    accession: str, factory: str
) -> None:
    """A statement-carrying 8-K or 8-K/A is served exactly like a 10-K."""
    view = getattr(_facade(accession).statements, factory)()
    assert view.status is QueryStatus.REPORTED
    assert view.message == ""
    assert view.root is not None
    assert len(view.nodes) > 1
    assert view.years != ()


def test_recast_comprehensive_income_is_served() -> None:
    """The recast files comprehensive income; its factory serves it."""
    view = _facade(_RECAST).statements.comprehensive_income_statement()
    assert view.status is QueryStatus.REPORTED
    assert view.root is not None
    assert len(view.nodes) > 1


def test_yyai_comprehensive_shell_is_outside_the_absence_trigger() -> None:
    """AIRWA files no comprehensive root; that shell is out of scope.

    The trigger covers filings with no statement roles, not root discovery.
    """
    view = _facade(_YYAI_8KA).statements.comprehensive_income_statement()
    assert view.status is QueryStatus.UNAVAILABLE
    assert view.root is not None
    assert view.root.concept_qname == ""


def test_msft_10k_statement_status_is_reported() -> None:
    """The annual specimen's factories keep serving composed statements."""
    statements = _seed_facade("msft_2024_10k").statements
    view = statements.income_statement()
    assert view.status is QueryStatus.REPORTED
    assert view.root is not None
    assert view.root.concept_qname == "us-gaap:NetIncomeLoss"


def test_no_presentation_arcs_facade_still_serves_statements() -> None:
    """An empty catalog alone is not absence when composition finds a root."""
    statements = _seed_facade("msft_2024_10k", presentation=False).statements
    assert statements.by_category("statement") == ()
    view = statements.income_statement()
    assert view.status is QueryStatus.REPORTED
    assert view.root is not None
    assert view.root.concept_qname == "us-gaap:NetIncomeLoss"
