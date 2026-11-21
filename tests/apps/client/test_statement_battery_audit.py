"""Statement-view audit: built-in presets reproduce Step 3 battery facts."""

from __future__ import annotations

import pyarrow as pa

from edgar_sec.engine.xbrl.discovery.placement_slices import placement_slices
from edgar_sec.engine.xbrl.review.battery import BATTERY_SET
from edgar_sec.engine.xbrl.solve.antichain import AntiChainValidator
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy

from tests.apps.client.statement_battery_support import (
    _NODE_EXCLUDED,
    _NODE_EXCLUDED_ENTRIES,
    _SERIES_PINNED,
    _SLICE_ACCESSIONS,
    _SLICE_BY_KIND,
    _SLICE_EXTRA,
    _SLICE_PINNED,
    _entries,
    _facade,
    _graphs,
    _kind,
    _loaded,
    _nodes,
)


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
