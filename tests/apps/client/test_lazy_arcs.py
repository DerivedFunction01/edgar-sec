"""Tests pinning lazy arc loading and deferred facade surfaces."""

from __future__ import annotations

import pytest

from edgar_sec.apps.client import xbrl as xbrl_module
from edgar_sec.apps.client.kernel import FilingKernel
from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.engine.xbrl.solve.concept_table import build_cohort_table
from edgar_sec.engine.xbrl.storage.storage import (
    declarations_from_arrow_table,
    read_declarations_parquet,
)
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.engine.xbrl.solve.conftest import load_seed_cohort

_FIRMS = ("MSFT", "AAPL")


@pytest.fixture(scope="module")
def cohort() -> tuple:
    """Concept table over two seed filings, as the cohort tests build."""
    taxonomy = load_domain_taxonomy()
    entries = tuple(e for e in load_seed_cohort() if e.firm in _FIRMS)
    merged: dict[str, object] = {}
    for entry in entries:
        path = entry.facts_path.parent / "declarations.parquet"
        if path.exists():
            for decl in declarations_from_arrow_table(read_declarations_parquet(path)):
                merged[decl.concept_qname] = decl
    table = build_cohort_table(taxonomy, entries, declarations=tuple(merged.values()))
    return taxonomy, entries, table


class _CountingReaders:
    """Wraps the xbrl module's arc readers, counting invocations."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.counts = {"calculation": 0, "presentation": 0, "definition": 0}
        for kind, name in (
            ("calculation", "calculation_arcs_from_arrow_table"),
            ("presentation", "presentation_arcs_from_arrow_table"),
            ("definition", "definition_arcs_from_arrow_table"),
        ):
            original = getattr(xbrl_module, name)

            def counting(table, _kind=kind, _original=original):
                self.counts[_kind] += 1
                return _original(table)

            monkeypatch.setattr(xbrl_module, name, counting)


def test_cohort_facade_loads_no_arcs_until_a_surface_walks_them(
    cohort, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify fact-only use reads no arc parquet; each set loads once."""
    _taxonomy, entries, table = cohort
    readers = _CountingReaders(monkeypatch)
    entry = next(e for e in entries if e.firm == "MSFT")
    facade = Xbrl.from_cohort(table, entries, entry.accession)
    assert readers.counts == {"calculation": 0, "presentation": 0, "definition": 0}

    assert len(facade.facts) > 0
    hits = facade.search("revenue").hits
    assert hits
    assert readers.counts == {"calculation": 0, "presentation": 0, "definition": 0}

    view = facade.statements.income_statement()
    assert view.root is not None
    assert readers.counts["calculation"] == 1
    assert readers.counts["presentation"] == 0
    assert readers.counts["definition"] == 0

    facade.locate(hits[0].qname)
    assert readers.counts["presentation"] == 1

    facade.statements.equity_rollforward()
    assert readers.counts["definition"] == 1

    facade.statements.balance_sheet()
    facade.locate(hits[0].qname)
    assert readers.counts == {"calculation": 1, "presentation": 1, "definition": 1}


def test_cohort_facade_linkbases_materialize_the_full_arcs(cohort) -> None:
    """Verify the raw linkbases accessor returns the deferred arcs."""
    _taxonomy, entries, table = cohort
    entry = next(e for e in entries if e.firm == "MSFT")
    facade = Xbrl.from_cohort(table, entries, entry.accession)
    assert facade.linkbases is not None
    assert facade.linkbases.calculation_arcs
    assert facade.linkbases.presentation_arcs
    assert facade.linkbases.calculation_arcs == facade._kernel.calculation_arcs


def test_financials_surface_is_built_on_first_access(
    cohort, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify constructing a facade does not build its financials."""
    _taxonomy, entries, table = cohort
    built: list[object] = []
    original = xbrl_module.XbrlFinancials

    def counting(*args, **kwargs):
        instance = original(*args, **kwargs)
        built.append(instance)
        return instance

    monkeypatch.setattr(xbrl_module, "XbrlFinancials", counting)
    entry = next(e for e in entries if e.firm == "AAPL")
    facade = Xbrl.from_cohort(table, entries, entry.accession)
    assert facade.search("revenue").hits
    assert built == []
    assert facade.financials.revenue is not None
    assert len(built) == 1
    assert facade.financials is built[0]


def test_kernel_defers_arc_suppliers_and_composer() -> None:
    """Verify a kernel resolves each supplier once, at first access."""
    taxonomy = load_domain_taxonomy()
    calls = {"calculation": 0, "presentation": 0}

    def calc() -> tuple:
        calls["calculation"] += 1
        return ()

    def pres() -> tuple:
        calls["presentation"] += 1
        return ()

    kernel = FilingKernel((), calc, taxonomy, presentation_arcs=pres)
    assert calls == {"calculation": 0, "presentation": 0}
    assert kernel.presentation_arcs == ()
    assert kernel.presentation_arcs == ()
    assert calls == {"calculation": 0, "presentation": 1}
    assert kernel.composer is kernel.composer
    assert calls["calculation"] == 1
    assert kernel.calculation_arcs == ()
    assert calls["calculation"] == 1
