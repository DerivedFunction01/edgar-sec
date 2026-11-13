"""Cascade behaviour: specific winners, evidence tier, residual."""

from __future__ import annotations

from edgar_sec.domain.forms.families.annual.location import location_priors
from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.classify import (
    TableKind,
    candidate_scores,
    classify_filing,
    classify_table,
)
from edgar_sec.engine.tables.extraction.context import (
    NoteRef,
    SectionRef,
    TableContext,
)
from edgar_sec.engine.tables.extraction.policy import (
    ClassificationPolicy,
    default_policy,
)
from edgar_sec.engine.tables.extraction.typed_rows import (
    CaptionInfo,
    ColumnPeriod,
    RowKind,
    TypedRow,
    TypedTable,
    structure_table,
)

_BALANCE_SHEET = (
    "Assets",
    "Current assets",
    "Cash and cash equivalents",
    "Total current assets",
    "Total assets",
    "Liabilities",
    "Current liabilities",
    "Total current liabilities",
    "Total liabilities",
    "Total stockholders' equity",
    "Total liabilities and stockholders' equity",
)


def _geometry() -> TableGeometry:
    return TableGeometry(
        table_index=0,
        render_result=TableRenderResult(
            ascii_text="",
            resolved_grid=ResolvedGrid(
                rows=(), column_alignments=(), column_widths=(), header_row_count=0
            ),
            confidence=1.0,
        ),
    )


def _table(
    labels: tuple[str, ...],
    *,
    caption_titles: tuple[str, ...] = (),
    note: NoteRef | None = None,
    section_item: str | None = None,
    kinds: tuple[RowKind, ...] | None = None,
) -> TypedTable:
    context = TableContext(
        geometry=_geometry(),
        section=SectionRef(section_item, None) if section_item else None,
        note=note,
    )
    rows = tuple(
        TypedRow(
            label=label,
            values=(1.0,),
            kind=kinds[index] if kinds else RowKind.DATA,
            raw=(label, "1"),
        )
        for index, label in enumerate(labels)
    )
    return TypedTable(
        context=context,
        caption=CaptionInfo(
            lines=(),
            company=None,
            titles=caption_titles,
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


def test_balance_sheet_spine_wins_with_classified_flavor() -> None:
    result = classify_table(_table(_BALANCE_SHEET))
    assert result.family == "balance_sheet"
    assert result.flavor == "classified"
    assert result.kind is TableKind.STATEMENT
    assert any(entry.group == "sequence" for entry in result.evidence)


def test_eps_specific_rule_beats_income_evidence() -> None:
    table = _table(
        (
            "Net income",
            "Numerator for basic earnings per share",
            "Denominator for basic earnings per share",
            "Denominator for diluted earnings per share",
        )
    )
    result = classify_table(table)
    assert result.family == "eps_reconciliation"
    assert result.tier == "specific"


def test_deferred_tax_labels_win_as_note_detail() -> None:
    table = _table(
        (
            "Deferred tax assets",
            "Valuation allowance",
            "Total deferred tax assets",
            "Deferred tax liabilities",
            "Total deferred tax liabilities",
        ),
        note=NoteRef(5, "NOTE 5", "Income Taxes"),
    )
    result = classify_table(table)
    assert result.family == "deferred_tax"
    assert result.kind is TableKind.NOTE_DETAIL


def test_fair_value_caption_anchor_wins() -> None:
    table = _table(
        ("Cash", "Money market funds", "Total"),
        caption_titles=("Fair Value Measurements",),
    )
    assert classify_table(table).family == "fair_value"


def test_income_flavor_follows_the_gross_profit_line() -> None:
    labels = (
        "Revenues",
        "Cost of revenues",
        "Gross profit",
        "Operating expenses",
        "Total operating expenses",
        "Operating income",
        "Net income",
    )
    assert classify_table(_table(labels)).flavor == "multi_step"
    single = tuple(label for label in labels if label != "Gross profit")
    result = classify_table(_table(single))
    assert result.family == "income_statement"
    assert result.flavor == "single_step"


def test_cash_flow_indirect_flavor() -> None:
    table = _table(
        (
            "Net income",
            "Adjustments to reconcile net income to net cash",
            "Depreciation and amortization",
            "Net cash provided by operating activities",
            "Net cash used in investing activities",
            "Net cash provided by financing activities",
        )
    )
    result = classify_table(table)
    assert result.family == "cash_flow"
    assert result.flavor == "indirect"


def test_parenthetical_rows_make_a_parenthetical_kind() -> None:
    table = _table(
        ("(see note 5)", "(in thousands)"),
        kinds=(RowKind.PARENTHETICAL, RowKind.PARENTHETICAL),
    )
    assert classify_table(table).kind is TableKind.PARENTHETICAL


def test_unmatched_table_falls_to_residual_with_a_trail() -> None:
    result = classify_table(_table(("Random heading", "Another row")))
    assert result.family == "other"
    assert result.tier == "residual"
    assert any(entry.group == "residual" for entry in result.evidence)


def test_location_prior_tips_a_weak_table_only_when_injected() -> None:
    labels = ("Cash and cash equivalents", "Total liabilities")
    weak = _table(labels, section_item="ITEM 8")
    assert classify_table(weak).family == "other"
    policy = ClassificationPolicy(location_priors=(("balance_sheet", "ITEM 8", 1.0),))
    result = classify_table(weak, policy)
    assert result.family == "balance_sheet"
    assert any(entry.group == "location" for entry in result.evidence)


def _annual_policy() -> ClassificationPolicy:
    return ClassificationPolicy(
        specific=default_policy().specific,
        location_priors=location_priors("10-K"),
    )


def _share(family: str, item: str) -> float:
    return next(
        value
        for prior_family, prior_item, value in location_priors("10-K")
        if prior_family == family and prior_item == item
    )


def test_annual_priors_decide_a_vocabulary_poor_note_table() -> None:
    """Three landmark labels score 4.5, below the floor; the measured
    ITEM 1 location share is the deciding evidence."""
    table = _table(
        ("Cash and cash equivalents", "Total current assets", "Total liabilities"),
        note=NoteRef(4, "NOTE 4", "Acquisitions"),
        section_item="ITEM 1",
    )
    assert classify_table(table).family == "other"
    result = classify_table(table, _annual_policy())
    assert result.family == "balance_sheet"
    assert result.tier == "evidence"
    expected = 2.0 * _share("balance_sheet", "ITEM 1")
    assert abs(result.score - (4.5 + expected)) < 1e-9
    assert any(
        entry.group == "location" and abs(entry.points - expected) < 1e-9
        for entry in result.evidence
    )


def test_annual_priors_score_a_schedule_family_in_its_home_item() -> None:
    """The tax reconciliation's candidacy in ITEM 16 rises by exactly the
    measured location share; its vocabulary ceiling stays below the floor."""
    table = _table(
        ("State and local taxes", "Federal income tax", "Other, net"),
        note=NoteRef(9, "NOTE 9", "Income Taxes"),
        section_item="ITEM 16",
    )
    before = classify_table(table)
    after = classify_table(table, _annual_policy())
    assert before.family == after.family == "other"
    expected = 2.0 * _share("tax_reconciliation", "ITEM 16")
    assert abs(after.score - before.score - expected) < 1e-9
    assert any("tax_reconciliation" in entry.detail for entry in after.evidence)


def test_candidate_scores_expose_the_cascade_map() -> None:
    table = _table(_BALANCE_SHEET)
    scored = candidate_scores(table)
    winner = classify_table(table)
    score, evidence = scored["balance_sheet"]
    assert winner.family == "balance_sheet"
    assert score == winner.score
    assert evidence == winner.evidence[1:]


def test_repair_landmarks_score_deferred_tax() -> None:
    table = _table(
        (
            "Net operating loss carryforwards",
            "Less: valuation allowance",
            "Tax credit carryforwards",
            "Total deferred tax assets",
        )
    )
    score, evidence = candidate_scores(table)["deferred_tax"]
    assert score > 0.0
    assert any(
        entry.group == "landmark"
        and entry.detail == "less: valuation allowance"
        and entry.points == 1.2
        for entry in evidence
    )


def test_repair_veto_cuts_balance_sheet_score_by_the_zero_rate_points() -> None:
    base = candidate_scores(_table(_BALANCE_SHEET))["balance_sheet"][0]
    vetoed_table = _table((*_BALANCE_SHEET, "Total interest-bearing deposits"))
    vetoed = candidate_scores(vetoed_table)["balance_sheet"][0]
    assert base - vetoed == 6.0


def test_repair_envelope_points_land_inside_the_shape_bounds() -> None:
    labels = ("Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta")
    inside = candidate_scores(_table(labels))["income_statement"][0]
    assert inside == 0.5
    outside = candidate_scores(_table(labels[:6]))["income_statement"][0]
    assert outside == 0.0


def test_repair_tax_vocabulary_wins_on_evidence() -> None:
    table = _table(
        (
            "Nontaxable or nondeductible items",
            "State and local taxes",
            "Other adjustments",
        )
    )
    result = classify_table(table)
    assert result.family == "tax_reconciliation"
    assert result.tier == "evidence"
    assert any(
        entry.group == "label" and entry.detail == "nontaxable or nondeductible items"
        for entry in result.evidence
    )
    assert any(
        entry.group == "landmark"
        and entry.detail == "nontaxable or nondeductible items"
        and entry.points == 2.1
        for entry in result.evidence
    )


def test_note_title_claim_assigns_an_unclaimed_table() -> None:
    table = _table(
        ("Alpha item", "Beta item"),
        note=NoteRef(None, None, "Subsequent Events"),
    )
    result = classify_table(table)
    assert result.family == "subsequent_events"
    assert result.tier == "evidence"
    assert result.score == 5.0
    assert any(entry.group == "note" for entry in result.evidence)


def test_note_title_claim_stands_down_to_a_scored_family() -> None:
    table = _table(
        _BALANCE_SHEET,
        note=NoteRef(None, None, "Segment Reporting"),
    )
    result = classify_table(table)
    assert result.family == "balance_sheet"


def test_note_title_claim_never_overrides_the_specific_tier() -> None:
    table = _table(
        (
            "Net income",
            "Numerator for basic earnings per share",
            "Denominator for basic earnings per share",
            "Denominator for diluted earnings per share",
        ),
        note=NoteRef(None, None, "Subsequent Events"),
    )
    result = classify_table(table)
    assert result.family == "eps_reconciliation"
    assert result.tier == "specific"


_TAX_LABELS = (
    "Nontaxable or nondeductible items",
    "State and local taxes",
    "Other adjustments",
)


def test_filing_pass_demotes_a_satellite_before_the_first_anchor() -> None:
    anchor = _table(_BALANCE_SHEET, caption_titles=("Consolidated Balance Sheets",))
    results, scores = classify_filing([_table(_TAX_LABELS), anchor])
    assert results[0].family == "other"
    assert scores[0]["tax_reconciliation"] == 0.0
    assert any(
        entry.group == "context"
        and "precedes the first statement anchor" in entry.detail
        for entry in results[0].evidence
    )
    assert results[1].family == "balance_sheet"


def test_filing_pass_keeps_a_satellite_after_the_anchor() -> None:
    anchor = _table(_BALANCE_SHEET, caption_titles=("Consolidated Balance Sheets",))
    results, _ = classify_filing([anchor, _table(_TAX_LABELS)])
    assert results[1].family == "tax_reconciliation"
    assert results[1].tier == "evidence"


_EQUITY_GRID = (
    (
        "",
        "Common Stock",
        "",
        "Retained",
        "",
        "Accumulated Other Comprehensive",
        "",
        "Total Shareholders’",
    ),
    ("", "Shares", "", "Earnings", "", "Income (Loss)", "", "Equity"),
    ("Balance at December 31, 2023", "", "100", "", "500", "", "5", "605"),
    ("Net income", "", "", "", "50", "", "", "50"),
    ("Other comprehensive loss", "", "", "", "", "", "(5)", "(5)"),
    ("Dividends declared", "", "", "", "(20)", "", "", "(20)"),
    ("Issuance of common stock", "", "10", "", "", "", "", "10"),
    ("Repurchase of common stock", "", "(2)", "", "", "", "", "(2)"),
    ("Balance at December 31, 2024", "", "108", "", "530", "", "0", "638"),
)

_SIGNATURE_GRID = (
    ("SIGNATURES",),
    (
        "Pursuant to the requirements of Section 13 or 15(d) of the "
        "Securities Exchange Act of 1934, the registrant has duly caused "
        "this report to be signed on its behalf by the undersigned.",
    ),
    (
        "By: /s/ Jane Roe",
        "Jane Roe",
        "President and Chief Executive Officer",
        "November 10, 2026",
    ),
)


def _grid_table(
    rows: tuple[tuple[str, ...], ...],
    *,
    section: SectionRef | None = None,
    region: str | None = None,
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
    context = TableContext(geometry=geometry, section=section, region=region)
    return structure_table(context)


def test_structure_channel_assigns_vocabulary_free_equity_grid() -> None:
    table = _grid_table(_EQUITY_GRID)
    scores = candidate_scores(table)
    score, evidence = scores["equity_statement"]
    structure = [entry for entry in evidence if entry.group == "structure"]
    assert {entry.detail for entry in structure} == {
        "component_columns",
        "rollforward_grid",
        "movement_grid",
        "complete_grid",
    }
    assert score >= 5.37
    result = classify_table(table)
    assert result.family == "equity_statement"
    assert result.tier == "evidence"


def test_stamped_signature_region_forces_residual() -> None:
    table = _grid_table(
        (
            ("Consolidated Balance Sheets",),
            ("Cash and cash equivalents", "100"),
            ("Total assets", "100"),
        ),
        region="signature",
    )
    result = classify_table(table)
    assert result.family == "other"
    assert result.tier == "region"


def test_filing_gate_clears_trailing_signature_geometry() -> None:
    anchor = _grid_table(
        (
            ("Consolidated Balance Sheets",),
            ("Cash and cash equivalents", "100"),
            ("Total assets", "100"),
        ),
        section=SectionRef("ITEM 8", "Financial Statements"),
    )
    signature = _grid_table(_SIGNATURE_GRID)
    results, scores = classify_filing([anchor, signature])
    assert results[0].family == "balance_sheet"
    assert results[1].family == "other"
    assert results[1].tier == "region"
    assert scores[1] == {}
