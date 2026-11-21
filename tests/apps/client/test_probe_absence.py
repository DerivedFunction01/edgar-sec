"""Statement absence posture on seed specimens: honest absence, not shells."""

from __future__ import annotations

import pyarrow.parquet as pq

from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.schema.models import FilingXbrl, LinkbaseBundle
from edgar_sec.engine.xbrl.solve.query import QueryStatus
from edgar_sec.engine.xbrl.storage.storage import presentation_arcs_from_arrow_table
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.engine.xbrl.solve.conftest import (
    load_seed_calculation_arcs,
    load_seed_facts,
)
from tests.support.corpus import bundle_dir


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
