"""PPE seat kind: the priced rule's specimen shapes.
Pins transcribe the depth lane's Phase 2 leg definitions.
"""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.core.text.context import TableContext
from edgar_sec.engine.tables.extraction.form_tests.form_tests import evaluate_form_tests
from edgar_sec.engine.tables.extraction.evidence.balance_sheet.ppe_evidence import (
    PpeText,
    legs_for,
)
from edgar_sec.engine.tables.extraction.specs.families.ppe_specs import (
    PPE_EVIDENCE_SPECS,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import (
    TypedTable,
    structure_table,
)

TEST_ID = "ppe_evidence"
SPEC = PPE_EVIDENCE_SPECS["ppe"]


def _table(
    rows: tuple[tuple[str, ...], ...],
    *,
    prose_before: str = "",
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
    context = TableContext(
        geometry=geometry, caption_stack=(), prose_before=prose_before
    )
    return structure_table(context)


def _outcome(table: TypedTable):
    return next(o for o in evaluate_form_tests(table) if o.test_id == TEST_ID)


def _legs(table: TypedTable):
    return legs_for(PpeText.from_table(table), SPEC)


def test_core_with_total_net_label_seats_as_newcore_lg() -> None:
    table = _table(
        (
            ("Land", "100"),
            ("Building", "200"),
            ("Machinery and equipment", "50"),
            ("Accumulated depreciation", "(80)"),
            ("Total, net", "270"),
        )
    )
    legs = _legs(table)
    assert legs.classes2 and legs.contra and legs.net_label and legs.net2
    assert legs.newcore and legs.newcore_lg and legs.claim
    outcome = _outcome(table)
    assert outcome.passed
    assert outcome.detail == "seat leg: newcore_lg"


def test_bare_total_after_contra_seats_via_net_bare() -> None:
    # The HP shape: the net row is an unlabeled total
    # closing directly under the contra row.
    table = _table(
        (
            ("Land", "10"),
            ("Building", "20"),
            ("Accumulated depreciation", "(5)"),
            ("", "25"),
        )
    )
    legs = _legs(table)
    assert legs.net_bare and not legs.net_label and not legs.net_close
    assert legs.newcore_lg and _outcome(table).passed


def test_balance_sheet_block_with_net_line_seats_on_the_face_form() -> None:
    table = _table(
        (
            ("Cash", "1"),
            ("Land", "10"),
            ("Building", "20"),
            ("Accumulated depreciation", "(5)"),
            ("Property and equipment, net", "25"),
            ("Total assets", "100"),
        )
    )
    legs = _legs(table)
    assert legs.net_close and not legs.bs_guard and not legs.newcore
    assert legs.face_form and legs.claim and _outcome(table).passed


def test_lease_mimic_is_shed_by_the_lease_guard_only() -> None:
    table = _table(
        (
            ("Land", "10"),
            ("Building", "20"),
            ("Accumulated depreciation", "(5)"),
            ("Total, net", "25"),
            ("Total lease liabilities", "30"),
        )
    )
    legs = _legs(table)
    assert legs.newcore and not legs.lease_guard and not legs.newcore_lg
    assert not legs.claim and not _outcome(table).passed


def test_columnar_contra_net_seats_as_col_form() -> None:
    table = _table(
        (
            ("", "Cost", "Accumulated Depreciation", "Net Book Value"),
            ("Land", "100", "(10)", "90"),
            ("Building", "200", "(20)", "180"),
        )
    )
    legs = _legs(table)
    assert not legs.contra and legs.contra_all and legs.net_col
    assert legs.col_form and legs.claim
    assert _outcome(table).detail == "seat leg: col_form"


def test_single_class_header_form_seats_as_col1_form() -> None:
    table = _table(
        (
            ("", "Gross carrying amount", "Accumulated depreciation", "Net book value"),
            ("Land", "100", "(10)", "90"),
        )
    )
    legs = _legs(table)
    assert legs.class_rows == 1 and legs.col1_form and legs.claim
    assert _outcome(table).detail == "seat leg: col1_form"


def test_schedule_iii_register_seats_as_s3_form() -> None:
    table = _table(
        (
            ("", "Initial cost", "Encumbrances", "Accumulated depreciation"),
            ("Iron Mountain facility", "100", "0", "(10)"),
            ("Second property", "50", "0", "(5)"),
        )
    )
    legs = _legs(table)
    assert legs.class_rows == 0 and legs.s3_form and legs.claim
    assert _outcome(table).detail == "seat leg: s3_form"


def test_real_estate_gross_rollforward_seats_as_roll_form() -> None:
    table = _table(
        (
            ("Gross carrying amount of real estate, beginning of year", "100"),
            ("Additions", "10"),
            ("Gross carrying amount of real estate, end of year", "110"),
        )
    )
    legs = _legs(table)
    assert legs.bookend_r2 and legs.roll_form and legs.claim
    assert _outcome(table).detail == "seat leg: roll_form"


def test_rights_depletion_form_seats_as_rights_form() -> None:
    table = _table(
        (
            ("Mineral rights", "100"),
            ("Land rights", "50"),
            ("Depletion", "(10)"),
            ("Net mineral rights", "90"),
        )
    )
    legs = _legs(table)
    assert legs.rights_form and legs.claim
    assert _outcome(table).detail == "seat leg: rights_form"


def test_single_class_component_seats_as_comp_form() -> None:
    table = _table(
        (
            ("Rental equipment", "100"),
            ("Accumulated depreciation", "(30)"),
            ("Net", "70"),
        ),
        prose_before=(
            "Rental fleet included in property and equipment, net of "
            "accumulated depreciation, in the balance sheet."
        ),
    )
    legs = _legs(table)
    assert legs.class_rows == 1 and not legs.classes2 and legs.comp_form
    assert _outcome(table).detail == "seat leg: comp_form"


def test_held_for_sale_shape_is_the_priced_admission() -> None:
    # The named FP :32 shape: a held-for-sale major-classes
    # table whose stub lacks the words "total assets"; the
    # seat admits it, exactly as priced.
    table = _table(
        (
            ("Land", "10"),
            ("Buildings and tenant improvements", "20"),
            ("Less accumulated depreciation", "(5)"),
            ("Net real estate assets", "25"),
        )
    )
    legs = _legs(table)
    assert legs.newcore_lg and legs.claim
    assert _outcome(table).passed


def test_outcome_carries_the_seat_kind_and_points() -> None:
    outcome = _outcome(
        _table(
            (
                ("Land", "100"),
                ("Building", "200"),
                ("Accumulated depreciation", "(80)"),
                ("Total, net", "220"),
            )
        )
    )
    assert outcome.family == "ppe"
    assert outcome.kind == "ppe_evidence"
    assert outcome.points == 3.0
    assert outcome.evaluable


def test_specific_only_schedule_seats_as_newcore_lg() -> None:
    table = _table(
        (
            ("Flight equipment", "100"),
            ("Rotable parts", "20"),
            ("Accumulated depreciation", "(30)"),
            ("Property and equipment, net", "90"),
        )
    )
    legs = _legs(table)
    assert legs.class_rows == 3 and legs.newcore_lg and legs.claim
    assert _outcome(table).passed


def test_specific_rollforward_seats_as_roll_form() -> None:
    table = _table(
        (
            ("Flight equipment, beginning of year", "100"),
            ("Additions", "10"),
            ("Flight equipment, end of year", "110"),
            ("Aircraft, beginning of year", "50"),
            ("Aircraft, end of year", "55"),
        )
    )
    legs = _legs(table)
    assert legs.bookend_r2 and legs.roll_form and legs.claim
    assert _outcome(table).detail == "seat leg: roll_form"


def test_variant_plant_and_equipment_net_close_seats() -> None:
    table = _table(
        (
            ("Utility plant", "100"),
            ("Plant in service", "200"),
            ("Accumulated depreciation", "(50)"),
            ("Plant and equipment, net", "250"),
        )
    )
    legs = _legs(table)
    assert legs.net_close and legs.newcore_lg and legs.claim
    assert _outcome(table).passed


def test_specific_terms_without_contra_or_net_do_not_seat() -> None:
    table = _table(
        (
            ("Flight equipment", "100"),
            ("Aircraft", "50"),
            ("Total flight operations", "150"),
        )
    )
    legs = _legs(table)
    assert legs.class_rows == 2 and not legs.claim
    assert not _outcome(table).passed


def test_empty_grid_is_unevaluable() -> None:
    outcome = _outcome(_table(()))
    assert not outcome.passed
    assert not outcome.evaluable
    assert outcome.detail == "no grid rows"
