"""Fixture guard: assembled statements against solved corpus roles."""

from __future__ import annotations

import json
from pathlib import Path

from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.assembly import assemble
from edgar_sec.engine.tables.extraction.context import TableContext
from tests.support import fixture_path

_CORPUS = fixture_path("table_extraction_corpus")
_COOPER = "0000024491-19-000016.json"


def _load_filing(name: str) -> tuple[list[TableContext], dict[int, str | None]]:
    filing = json.loads((Path(_CORPUS) / name).read_text(encoding="utf-8"))
    contexts: list[TableContext] = []
    golds: dict[int, str | None] = {}
    for record in filing["geometries"]:
        geometry = TableGeometry(
            table_index=record["table_index"],
            render_result=TableRenderResult(
                ascii_text="",
                resolved_grid=ResolvedGrid(
                    rows=tuple(tuple(row) for row in record["rows"]),
                    column_alignments=(),
                    column_widths=(),
                    header_row_count=record["header_row_count"],
                ),
                confidence=1.0,
            ),
        )
        contexts.append(TableContext.from_record(geometry, record))
        label = record.get("label")
        if label and label["split"] == "derivation":
            golds[record["table_index"]] = label["final_family"]
    return contexts, golds


def test_cooper_tire_split_balance_sheet_is_one_main() -> None:
    contexts, golds = _load_filing(_COOPER)
    assembly = assemble(contexts)
    hosts = [
        table for table in assembly.tables if 6 in table.members or 7 in table.members
    ]
    (host,) = hosts
    assert host.family == "balance_sheet"
    assert host.role == "main"
    assert set(host.members) >= {6, 7}
    assert golds[6] == golds[7] == "balance_sheet"


def test_cooper_tire_core_mains_carry_their_solved_family() -> None:
    contexts, golds = _load_filing(_COOPER)
    assembly = assemble(contexts)
    mains = {table.family: table for table in assembly.tables if table.role == "main"}
    for family in ("income_statement", "balance_sheet", "cash_flow"):
        assert family in mains
        assert golds[mains[family].members[0]] == family


def test_every_geometry_is_accounted_exactly_once() -> None:
    contexts, _ = _load_filing(_COOPER)
    assembly = assemble(contexts)
    accounted: list[int] = []
    for table in assembly.tables:
        accounted.extend(table.members)
        accounted.extend(table.section_members)
    accounted.extend(assembly.unassigned)
    assert sorted(accounted) == sorted(context.table_index for context in contexts)
    assert len(accounted) == len(set(accounted))
    assert len(assembly.assignments) == len(contexts)
