"""Inventory seat kind: the priced rule's specimen shapes.
Pins transcribe the Ruling 18 pass's priced leg definitions.
"""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.core.context import TableContext
from edgar_sec.engine.tables.extraction.form_tests.form_tests import evaluate_form_tests
from edgar_sec.engine.tables.extraction.evidence.inventory_evidence import (
    InventoryText,
    legs_for,
)
from edgar_sec.engine.tables.extraction.specs.inventory_specs import (
    INVENTORY_EVIDENCE_SPECS,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import (
    TypedTable,
    structure_table,
)

TEST_ID = "inventory_evidence"
SPEC = INVENTORY_EVIDENCE_SPECS["inventory"]


def _table(
    rows: tuple[tuple[str, ...], ...],
    *,
    caption_stack: tuple[str, ...] = (),
) -> TypedTable:
    geometry = TableGeometry(
        table_index=0,
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
    context = TableContext(geometry=geometry, caption_stack=caption_stack)
    return structure_table(context)


def _outcome(table: TypedTable):
    return next(o for o in evaluate_form_tests(table) if o.test_id == TEST_ID)


def _legs(table: TypedTable):
    return legs_for(InventoryText.from_table(table), SPEC)


def test_component_class_core_seats_without_finished() -> None:
    table = _table(
        (
            ("Work in process", "100"),
            ("Raw materials", "50"),
            ("Other current assets", "10"),
            ("Total inventories", "160"),
        )
    )
    legs = _legs(table)
    assert legs.core and not legs.finished
    outcome = _outcome(table)
    assert outcome.passed
    assert outcome.detail == "core: component classes to total"


def test_finished_goods_stub_seats_without_core() -> None:
    table = _table(
        (
            ("Finished goods", "100"),
            ("Widgets", "10"),
            ("Gadgets", "5"),
        )
    )
    legs = _legs(table)
    assert legs.finished and not legs.core
    outcome = _outcome(table)
    assert outcome.passed
    assert outcome.detail == "finished-goods stub vocabulary"


def test_total_row_counts_as_a_class_row() -> None:
    table = _table(
        (
            ("Raw materials", "50"),
            ("Total inventories", "160"),
        )
    )
    legs = _legs(table)
    assert legs.class_rows == 2
    assert legs.core


def test_two_class_rows_without_total_or_finished_fail() -> None:
    table = _table(
        (
            ("Work in process", "100"),
            ("Raw materials", "50"),
            ("Subtotal", "150"),
        )
    )
    legs = _legs(table)
    assert legs.classes2 and not legs.total_line and not legs.finished
    assert not _outcome(table).passed


def test_single_class_row_fails() -> None:
    table = _table(
        (
            ("Inventory", "100"),
            ("Total assets", "500"),
        )
    )
    legs = _legs(table)
    assert legs.class_rows == 1
    assert not _outcome(table).passed


def test_finished_in_caption_only_does_not_seat() -> None:
    # The priced leg reads the stub only; framing text is not
    # the family's seat surface.
    table = _table(
        (
            ("Widgets", "1"),
            ("Gadgets", "2"),
            ("Total", "3"),
        ),
        caption_stack=("Finished goods summary",),
    )
    legs = _legs(table)
    assert not legs.finished and not legs.core
    assert not _outcome(table).passed


def test_statement_stubs_fail_with_zero_class_rows() -> None:
    table = _table(
        (
            ("Cash and cash equivalents", "100"),
            ("Accounts receivable", "50"),
            ("Total assets", "500"),
        )
    )
    outcome = _outcome(table)
    assert not outcome.passed
    assert outcome.detail == "no seat leg (class rows 0)"


def test_outcome_carries_the_seat_kind_and_points() -> None:
    table = _table((("Finished goods", "100"),))
    outcome = _outcome(table)
    assert outcome.family == "inventory"
    assert outcome.kind == "inventory_evidence"
    assert outcome.points == 3.0
    assert outcome.evaluable


def test_empty_grid_is_unevaluable() -> None:
    outcome = _outcome(_table(()))
    assert not outcome.passed
    assert not outcome.evaluable
    assert outcome.detail == "no grid rows"
