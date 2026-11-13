"""Coverage re-drive admissions: priced figures and behaviour."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.calibration import PATTERNS, PROSE_PATTERNS
from edgar_sec.engine.tables.extraction.classify import classify_table
from edgar_sec.engine.tables.extraction.context import (
    SectionRef,
    TableContext,
)
from edgar_sec.engine.tables.extraction.registry import (
    FAMILY_PRIORITY,
    LANDMARKS,
    PROV_COVERAGE_DISCOVERY,
    PROV_COVERAGE_SEED,
    SEQUENCES,
)
from edgar_sec.engine.tables.extraction.typed_rows import (
    CaptionInfo,
    ColumnPeriod,
    RowKind,
    TypedRow,
    TypedTable,
)

# (family, term, kind, support, share, labelled exclusivity, provenance)
ADMITTED_PATTERNS = (
    ("aoci", "amounts reclassified", "token", 4, 0.5, 1.0, PROV_COVERAGE_SEED),
    ("aoci", "aoci", "label", 3, 0.375, 1.0, PROV_COVERAGE_SEED),
    (
        "aoci",
        "balance at beginning of period",
        "label",
        3,
        0.375,
        0.6,
        PROV_COVERAGE_DISCOVERY,
    ),
    (
        "aoci",
        "balance at end of period",
        "label",
        4,
        0.5,
        0.571,
        PROV_COVERAGE_DISCOVERY,
    ),
    ("aoci", "before reclassifications", "token", 4, 0.5, 1.0, PROV_COVERAGE_SEED),
    ("aoci", "reclassifications", "token", 4, 0.5, 1.0, PROV_COVERAGE_SEED),
    ("aoci", "reclassified", "token", 4, 0.5, 0.667, PROV_COVERAGE_SEED),
    (
        "equity_statement",
        "foreign currency translation adjustments",
        "label",
        3,
        0.333,
        0.75,
        PROV_COVERAGE_DISCOVERY,
    ),
    ("intangibles", "patents", "label", 3, 0.75, 0.75, PROV_COVERAGE_SEED),
    ("pension", "interest cost", "label", 4, 1.0, 1.0, PROV_COVERAGE_SEED),
    ("pension", "service cost", "label", 4, 1.0, 0.8, PROV_COVERAGE_SEED),
    (
        "stock_comp_rollforward",
        "cancelled",
        "label",
        6,
        0.75,
        0.857,
        PROV_COVERAGE_DISCOVERY,
    ),
    (
        "stock_comp_rollforward",
        "exercised",
        "label",
        7,
        0.875,
        0.636,
        PROV_COVERAGE_SEED,
    ),
    (
        "stock_comp_rollforward",
        "forfeited",
        "label",
        5,
        0.625,
        0.833,
        PROV_COVERAGE_SEED,
    ),
    (
        "stock_comp_rollforward",
        "granted",
        "label",
        8,
        1.0,
        1.0,
        PROV_COVERAGE_SEED,
    ),
)

# (family, ngram, support, labelled exclusivity)
ADMITTED_PROSE = (
    ("stock_comp_rollforward", "aggregate intrinsic value", 3, 1.0),
    ("stock_comp_rollforward", "grant date", 5, 0.833),
    ("stock_comp_rollforward", "intrinsic value", 4, 1.0),
)


def _table(labels: tuple[str, ...]) -> TypedTable:
    context = TableContext(
        geometry=TableGeometry(
            table_index=0,
            render_result=TableRenderResult(
                ascii_text="",
                resolved_grid=ResolvedGrid(
                    rows=(),
                    column_alignments=(),
                    column_widths=(),
                    header_row_count=0,
                ),
                confidence=1.0,
            ),
        ),
        section=SectionRef(None, None),
        note=None,
    )
    rows = tuple(
        TypedRow(label=label, values=(1.0,), kind=RowKind.DATA, raw=(label, "1"))
        for label in labels
    )
    return TypedTable(
        context=context,
        caption=CaptionInfo(
            lines=(),
            company=None,
            titles=(),
            audit_status=None,
            scale=None,
            continued=False,
            consumed_rows=0,
        ),
        periods=(
            ColumnPeriod(1, None, "2024", "2024"),
            ColumnPeriod(2, None, "2023", "2023"),
        ),
        rows=rows,
        scale=None,
        header_rows=0,
        continued=False,
    )


def test_admitted_patterns_carry_their_measured_figures() -> None:
    by_key = {(spec.family, spec.term): spec for spec in PATTERNS}
    for (
        family,
        term,
        kind,
        support,
        share,
        exclusivity,
        provenance,
    ) in ADMITTED_PATTERNS:
        spec = by_key[(family, term)]
        assert (spec.kind, spec.support, spec.share) == (kind, support, share)
        assert spec.exclusivity == exclusivity
        assert spec.provenance == provenance


def test_admitted_prose_patterns_carry_their_measured_figures() -> None:
    by_key = {(spec.family, spec.ngram): spec for spec in PROSE_PATTERNS}
    for family, ngram, support, exclusivity in ADMITTED_PROSE:
        spec = by_key[(family, ngram)]
        assert (spec.window, spec.support) == ("after", support)
        assert spec.exclusivity == exclusivity
        assert spec.provenance == PROV_COVERAGE_SEED


def test_admitted_landmarks_and_sequences_are_registered() -> None:
    assert LANDMARKS["aoci"] == (
        "balance at end of period",
        "balance at beginning of period",
        "beginning balance",
        "ending balance",
    )
    assert LANDMARKS["equity_statement"] == (
        "foreign currency translation adjustments",
    )
    assert LANDMARKS["stock_comp_rollforward"] == ("granted", "exercised")
    sequences = {(spec.family, spec.terms): spec for spec in SEQUENCES}
    assert sequences[("stock_comp_rollforward", ("granted", "exercised"))].support == 6
    aoci_pairs = {terms for (family, terms) in sequences if family == "aoci"}
    assert aoci_pairs == {
        ("balance at beginning of period", "balance at end of period"),
        ("beginning balance", "ending balance"),
    }
    assert all(
        spec.provenance == PROV_COVERAGE_DISCOVERY
        for spec in sequences.values()
        if spec.family in ("aoci", "stock_comp_rollforward")
    )


def test_priority_places_schedule_families_ahead_of_balance_sheet() -> None:
    inserts = (
        "aoci",
        "cover_layout",
        "debt_maturity",
        "derivatives_hedging",
        "intangibles",
        "pension",
        "ppe",
        "shares_purchased",
        "stock_comp_rollforward",
    )
    anchor = FAMILY_PRIORITY.index("balance_sheet")
    assert FAMILY_PRIORITY[anchor - len(inserts) : anchor] == inserts
    scored = {spec.family for spec in PATTERNS if spec.family != "other"}
    scored |= set(LANDMARKS)
    assert scored <= set(FAMILY_PRIORITY)


def test_pension_cost_pair_classifies_as_pension() -> None:
    table = _table(("Service cost", "Interest cost", "Expected return on plan assets"))
    assert classify_table(table).family == "pension"


def test_stock_comp_rollforward_vocabulary_classifies() -> None:
    table = _table(("Granted", "Exercised", "Forfeited", "Cancelled"))
    assert classify_table(table).family == "stock_comp_rollforward"


def test_aoci_rollforward_classifies() -> None:
    table = _table(
        (
            "Balance at beginning of period",
            "Amounts reclassified",
            "Balance at end of period",
        )
    )
    assert classify_table(table).family == "aoci"


def test_patents_alone_stays_below_the_assignment_floor() -> None:
    """One label hit scores 3.25 against the 5.0 floor: the intangibles
    admission is inert without corroborating evidence."""
    table = _table(("Patents", "Trademark rights"))
    assert classify_table(table).family == "other"
