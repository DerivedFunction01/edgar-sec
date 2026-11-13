"""Assembly: grouping, relational arbitration, slot ranking."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.assembly import (
    SIGNAL_ASSEMBLY_INCOMPLETE,
    SIGNAL_BS_IDENTITY_FAILED,
    SIGNAL_KIND_UNCERTAIN,
    SIGNAL_SCALE_UNSTATED,
    assemble,
)
from edgar_sec.engine.tables.extraction.context import (
    NoteRef,
    TableContext,
)

_PERIODS = ("", "December 31, 2024", "December 31, 2023")

_BS_HEAD = (
    ("ACME CORP",),
    ("Consolidated Balance Sheets",),
    _PERIODS,
    ("Assets", "", ""),
    ("Cash and cash equivalents", "100", "90"),
    ("Total current assets", "100", "90"),
    ("Total assets", "100", "90"),
)
_BS_TAIL = (
    ("Consolidated Balance Sheets (continued)",),
    _PERIODS,
    ("Liabilities", "", ""),
    ("Total liabilities", "60", "50"),
    ("Total stockholders' equity", "40", "40"),
    ("Total liabilities and stockholders' equity", "100", "90"),
)
_BS_SMALL = (
    ("Balance Sheets",),
    _PERIODS,
    ("Total assets", "50", "40"),
    ("Total liabilities and stockholders' equity", "50", "40"),
)
_CONTINUED_QUIET = (
    ("(continued)",),
    _PERIODS,
    ("Other current liabilities", "10", "9"),
    ("Accrued expenses and other", "5", "4"),
)
_THIN_FRAGMENT = (
    _PERIODS,
    ("Total assets", "100", "90"),
)
_EVIDENCED_FRAGMENT = (
    _PERIODS,
    ("Total liabilities", "60", "50"),
    ("Total assets", "100", "90"),
)
_QUIET = (
    _PERIODS,
    ("Other liabilities", "10", "9"),
    ("Accrued expenses", "5", "4"),
)
_PAREN_FRAGMENT = (
    ("(continued)",),
    _PERIODS,
    ("(See Note 5)", ""),
    ("(Unaudited)", ""),
)
_INCOME = (
    ("Consolidated Statements of Income",),
    _PERIODS,
    ("Revenues", "100", "90"),
    ("Net income", "10", "9"),
)
_EQUITY_AOCI = (
    ("ACME CORP",),
    ("Consolidated Statements of Changes in Equity",),
    _PERIODS,
    ("Balance at beginning of period", "100", "90"),
    ("Other comprehensive income", "5", "4"),
    ("Amounts reclassified", "1", "1"),
    ("Balance at end of period", "106", "95"),
    ("Total stockholders' equity", "106", "95"),
)
_EQUITY_NOTE = (
    ("Statements of Changes in Equity",),
    _PERIODS,
    ("Balance, beginning", "100", "90"),
    ("Net income", "6", "5"),
    ("Balance, ending", "106", "95"),
)
_AOCI_NOTE = (
    ("Accumulated other comprehensive income",),
    _PERIODS,
    ("Balance at beginning of period", "10", "8"),
    ("Reclassifications", "1", "1"),
    ("Balance at end of period", "11", "9"),
)
_FAIR_VALUE = (
    ("Fair Value Measurements",),
    _PERIODS,
    ("Assets", "100", "90"),
    ("Total assets", "100", "90"),
    ("Total liabilities", "60", "50"),
    ("Total liabilities and stockholders' equity", "100", "90"),
)
_BS_BAD = (
    ("Balance Sheets",),
    _PERIODS,
    ("Total assets", "100", "90"),
    ("Total liabilities and stockholders' equity", "90", "80"),
)
_DEFERRED_TAX = (
    _PERIODS,
    ("Deferred tax assets", "10", "9"),
    ("Deferred tax liabilities", "4", "3"),
    ("Valuation allowance", "1", "1"),
)
_TAX_RECON = (
    _PERIODS,
    ("Statutory tax", "21", "20"),
    ("Local taxes", "2", "2"),
)
_EQUITY_CAPTURE = (
    ("Statements of changes in equity",),
    _PERIODS,
    ("Cash and cash equivalents", "100", "90"),
    ("Total assets", "100", "90"),
)
_BS_SPINE_BROKEN = (
    _PERIODS,
    ("Assets", "", ""),
    ("Cash and cash equivalents", "100", "90"),
    ("Total current assets", "100", "90"),
    ("Total assets", "100", "90"),
    ("Liabilities", "", ""),
    ("Total current liabilities", "60", "50"),
    ("Total liabilities", "60", "50"),
    ("Total stockholders' equity", "30", "30"),
    ("Total liabilities and stockholders' equity", "95", "85"),
)
_BS_ANCHOR_THIN = (
    ("Balance Sheets",),
    _PERIODS,
    ("Total assets", "50", "40"),
    ("Total liabilities and stockholders' equity", "45", "35"),
)


def _context(
    index: int,
    rows: tuple[tuple[str, ...], ...],
    *,
    note: NoteRef | None = None,
) -> TableContext:
    geometry = TableGeometry(
        table_index=index,
        render_result=TableRenderResult(
            ascii_text="",
            resolved_grid=ResolvedGrid(
                rows=rows,
                column_alignments=(),
                column_widths=(),
                header_row_count=0,
            ),
            confidence=1.0,
        ),
    )
    return TableContext(geometry=geometry, note=note)


def _tables(assembly, family: str):
    return [table for table in assembly.tables if table.family == family]


def test_split_statement_assembles_into_one_main() -> None:
    assembly = assemble([_context(6, _BS_HEAD), _context(7, _BS_TAIL)])
    (table,) = _tables(assembly, "balance_sheet")
    assert table.role == "main"
    assert table.members == (6, 7)
    assert SIGNAL_BS_IDENTITY_FAILED not in table.signals
    assert assembly.unassigned == ()


def test_residual_fragment_joins_on_a_continued_marker() -> None:
    assembly = assemble([_context(6, _BS_HEAD), _context(7, _CONTINUED_QUIET)])
    (table,) = _tables(assembly, "balance_sheet")
    assert table.members == (6, 7)
    assignment = {a.table_index: a for a in assembly.assignments}
    assert assignment[7].family == "balance_sheet"
    assert assignment[7].mechanism == "join"


def test_thin_fragment_does_not_join_on_period_continuity_alone() -> None:
    assembly = assemble([_context(6, _BS_HEAD), _context(7, _THIN_FRAGMENT)])
    (table,) = _tables(assembly, "balance_sheet")
    assert table.members == (6,)
    assert assembly.unassigned == (7,)


def test_evidenced_fragment_joins_on_period_continuity() -> None:
    assembly = assemble([_context(6, _BS_HEAD), _context(7, _EVIDENCED_FRAGMENT)])
    (table,) = _tables(assembly, "balance_sheet")
    assert table.members == (6, 7)


def test_quiet_zero_evidence_fragment_stays_unassigned() -> None:
    assembly = assemble([_context(6, _BS_HEAD), _context(7, _QUIET)])
    (table,) = _tables(assembly, "balance_sheet")
    assert table.members == (6,)
    assert assembly.unassigned == (7,)


def test_interleaved_residual_does_not_block_a_join() -> None:
    assembly = assemble(
        [_context(6, _BS_HEAD), _context(7, _QUIET), _context(8, _BS_TAIL)]
    )
    (table,) = _tables(assembly, "balance_sheet")
    assert table.members == (6, 8)
    assert assembly.unassigned == (7,)


def test_slot_ranking_names_one_main_and_a_variant() -> None:
    assembly = assemble(
        [_context(1, _BS_HEAD), _context(2, _INCOME), _context(3, _BS_SMALL)]
    )
    tables = _tables(assembly, "balance_sheet")
    assert len(tables) == 2
    roles = {table.members: table.role for table in tables}
    assert roles[(1,)] == "main"
    assert roles[(3,)] == "variant"


def test_containment_section_inside_a_parent_assignment() -> None:
    assembly = assemble([_context(3, _EQUITY_AOCI)])
    assert _tables(assembly, "aoci") == []
    (table,) = _tables(assembly, "equity_statement")
    assert table.sections == ("aoci",)
    assert "aoci" in table.tags


def test_note_colocated_subset_is_consumed_as_a_section() -> None:
    note = NoteRef(number=5, label=None, title="Equity")
    assembly = assemble(
        [_context(3, _EQUITY_NOTE, note=note), _context(4, _AOCI_NOTE, note=note)]
    )
    assert _tables(assembly, "aoci") == []
    (table,) = _tables(assembly, "equity_statement")
    assert table.sections == ("aoci",)
    assert table.section_members == (4,)
    assignment = {a.table_index: a for a in assembly.assignments}
    assert assignment[4].family == "aoci"
    assert assignment[4].mechanism == "section"


def test_subset_without_a_parent_stays_its_own_table() -> None:
    note = NoteRef(number=5, label=None, title="Equity")
    assembly = assemble([_context(4, _AOCI_NOTE, note=note)])
    (table,) = _tables(assembly, "aoci")
    assert table.role == "main"
    assert table.members == (4,)


def test_co_note_siblings_link_inside_their_note_group() -> None:
    note = NoteRef(number=7, label=None, title="Income Taxes")
    assembly = assemble(
        [
            _context(11, _DEFERRED_TAX, note=note),
            _context(12, _TAX_RECON, note=note),
        ]
    )
    assert len(_tables(assembly, "deferred_tax")) == 1
    assert len(_tables(assembly, "tax_reconciliation")) == 1
    (group,) = assembly.note_groups
    assert group.siblings == (("deferred_tax", "tax_reconciliation"),)
    assert any(d.kind == "co_note" for d in assembly.decisions)


def test_fair_value_table_serves_the_balance_sheet_dually() -> None:
    assembly = assemble([_context(9, _FAIR_VALUE)])
    assert _tables(assembly, "balance_sheet") == []
    (table,) = _tables(assembly, "fair_value")
    assert table.tags == ("fair_value", "balance_sheet")
    assert any(d.kind == "dual" for d in table.decisions)


def test_assembled_balance_sheet_identity_failure_is_signalled() -> None:
    assembly = assemble([_context(2, _BS_BAD)])
    (table,) = _tables(assembly, "balance_sheet")
    assert table.role == "main"
    assert SIGNAL_BS_IDENTITY_FAILED in table.signals


def test_assembled_row_bound_and_scale_signals() -> None:
    assembly = assemble([_context(5, _INCOME)])
    (table,) = _tables(assembly, "income_statement")
    assert SIGNAL_ASSEMBLY_INCOMPLETE in table.signals
    assert SIGNAL_SCALE_UNSTATED in table.signals


def test_mixed_member_kinds_raise_kind_uncertain() -> None:
    assembly = assemble([_context(6, _BS_HEAD), _context(7, _PAREN_FRAGMENT)])
    (table,) = _tables(assembly, "balance_sheet")
    assert table.members == (6, 7)
    assert SIGNAL_KIND_UNCERTAIN in table.signals


def test_anchor_only_group_gets_no_main() -> None:
    assembly = assemble([_context(1, _EQUITY_CAPTURE)])
    (table,) = _tables(assembly, "equity_statement")
    assert table.role == "variant"
    assert any(
        decision.kind == "slot" and "no main" in decision.detail
        for decision in table.decisions
    )


def test_evidence_group_outranks_anchor_group_for_main() -> None:
    assembly = assemble([_context(1, _BS_SPINE_BROKEN), _context(2, _BS_ANCHOR_THIN)])
    tables = _tables(assembly, "balance_sheet")
    assert len(tables) == 2
    roles = {table.members: table.role for table in tables}
    assert roles[(1,)] == "main"
    assert roles[(2,)] == "variant"


_BS_SECOND_SET = (
    ("Condensed Balance Sheets",),
    _PERIODS,
    ("Total assets", "50", "40"),
    ("Total liabilities and stockholders' equity", "45", "35"),
)
_BS_AGREEING = (
    ("Balance Sheets",),
    _PERIODS,
    ("Total assets", "100", "90"),
    ("Total liabilities and stockholders' equity", "95", "85"),
)


def test_variant_with_conflicting_totals_is_a_second_set() -> None:
    assembly = assemble(
        [
            _context(6, _BS_HEAD),
            _context(7, _BS_TAIL),
            _context(8, _INCOME),
            _context(9, _BS_SECOND_SET),
        ]
    )
    tables = _tables(assembly, "balance_sheet")
    assert len(tables) == 2
    variant = next(table for table in tables if table.role == "variant")
    assert "second_set" in variant.tags
    assert any(decision.kind == "second_set" for decision in variant.decisions)


def test_variant_sharing_the_main_totals_is_no_second_set() -> None:
    assembly = assemble(
        [
            _context(6, _BS_HEAD),
            _context(7, _BS_TAIL),
            _context(8, _INCOME),
            _context(9, _BS_AGREEING),
        ]
    )
    tables = _tables(assembly, "balance_sheet")
    assert len(tables) == 2
    variant = next(table for table in tables if table.role == "variant")
    assert "second_set" not in variant.tags
