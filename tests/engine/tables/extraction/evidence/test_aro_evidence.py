"""ARO evidence gate: registry data and the priced specimen shapes."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.evidence.aro_evidence import (
    AroText,
    apply_aro_assignment,
    aro_legs,
    evaluate_form_test_aro,
)
from edgar_sec.engine.tables.extraction.cascade.geometry_text import GeometryText
from edgar_sec.engine.tables.extraction.core.context import TableContext
from edgar_sec.engine.tables.extraction.specs.aro_evidence_specs import (
    ARO_ASSIGNMENT_SPEC,
    ARO_EVIDENCE_SPECS,
    ARO_EVIDENCE_SPECS_BY_TEST_ID,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_specs import (
    FORM_TEST_SPECS,
)
from edgar_sec.engine.tables.extraction.cascade.geometry_scoring import (
    ClaimGroup,
    CompetitionResult,
    FamilyScore,
)
from edgar_sec.engine.tables.extraction.core.profiles import (
    TEST_ARO_EVIDENCE,
    profile_for,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table

SPEC = ARO_EVIDENCE_SPECS["aro_rollforward"]
ENTRY = next(s for s in FORM_TEST_SPECS if s.family == "aro_rollforward")

Rows = tuple[tuple[str, ...], ...]


def _text(rows: Rows, caption: tuple[str, ...] = (), prose: str = ""):
    return AroText(
        caption=" ".join(caption),
        prose=prose,
        lines=tuple(" | ".join(row) for row in rows),
    )


def _verdict(rows: Rows, caption: tuple[str, ...] = (), prose: str = ""):
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
    context = TableContext(geometry=geometry, caption_stack=caption, prose_before=prose)
    return evaluate_form_test_aro(structure_table(context), ENTRY)


def test_gate_is_declared_as_form_test_data():
    assert ENTRY.kind == TEST_ARO_EVIDENCE
    assert ENTRY.points == 3.0
    assert ARO_EVIDENCE_SPECS_BY_TEST_ID[ENTRY.test_id] is SPEC
    profile = profile_for("aro_rollforward")
    assert profile is not None
    assert TEST_ARO_EVIDENCE in profile.form_tests


def test_filed_walk_admits():
    rows = (
        ("", "2024", "2023"),
        ("Balance at beginning of period", "$ 100", "$ 90"),
        ("Liabilities incurred", "10", "5"),
        ("Accretion expense", "5", "4"),
        ("Liabilities settled", "(3)", "(2)"),
        ("Balance at end of period", "$ 112", "$ 100"),
    )
    verdict = _verdict(rows, caption=("Asset Retirement Obligations",))
    assert verdict.admitted


def test_carrying_amount_walk_admits_via_f2c():
    rows = (
        ("", "2014", "", "", "2013", ""),
        ("Carrying Amount at Beginning of Period", "$", "761,898", "", "$", "665,944"),
        ("Liabilities Incurred", "123,849", "", "", "103,284", ""),
        ("Liabilities Settled (1)", "(247,422)", "", "", "(70,510)", ""),
        ("Accretion", "41,489", "", "", "35,180", ""),
        ("Revisions", "82,885", "", "", "38,552", ""),
        ("Foreign Currency Translations", "(9,981)", "", "", "(10,552)", ""),
        ("Carrying Amount at End of Period", "$", "752,718", "", "$", "761,898"),
        ("Current Portion", "$", "11,814", "", "$", "43,857"),
        ("Noncurrent Portion", "$", "740,904", "", "$", "718,041"),
    )
    prose = (
        "15. Asset Retirement Obligations\nThe following table presents "
        "the reconciliation of the beginning and ending aggregate "
        "carrying amounts of asset retirement obligations:"
    )
    legs = aro_legs(_text(rows, prose=prose), SPEC)
    assert not legs["bookend_f2"]
    assert legs["bookend_f2c"] and legs["claim"]
    assert _verdict(rows, prose=prose).admitted


def test_abbreviation_subject_admits_via_s2_and_bare_pair():
    rows = (
        ("ARO, beginning of period", "100"),
        ("Liabilities settled", "(10)"),
        ("Accretion expense", "5"),
        ("ARO, end of period", "95"),
    )
    legs = aro_legs(_text(rows), SPEC)
    assert not legs["subject_lead"]
    assert legs["subject2"] and legs["bare_bookend"] and legs["claim"]


def test_minimal_walk_admits_on_accretion_alone():
    rows = (
        ("Balance, beginning of period", "100"),
        ("Accretion", "5"),
        ("Balance, end of period", "105"),
    )
    text = _text(rows, caption=("Asset Retirement Obligations",))
    legs = aro_legs(text, SPEC)
    assert legs["movement_types"] == ("accretion",)
    assert legs["claim"]


def test_no_accretion_walk_admits():
    rows = (
        ("Balance at beginning of year", "100"),
        ("Liabilities incurred", "20"),
        ("Foreign currency translation adjustment", "3"),
        ("Balance at end of year", "123"),
    )
    legs = aro_legs(_text(rows, caption=("Asset Retirement Obligations",)), SPEC)
    assert not legs["accretion"]
    assert legs["claim"]


def test_standardized_measure_walk_refused_by_exclusion():
    rows = (
        ("", "2016", "2015", "2014"),
        ("Balance at beginning of year", "$ 1,392", "$ 6,421", "$ 9,417"),
        ("Sales, net of production expenses", "(831)", "(928)", "(3,062)"),
        ("Accretion of discount", "139", "797", "1,195"),
        ("Revisions of quantity estimates", "12", "(1,170)", "399"),
        ("Balance at end of year", "$ 1,000", "$ 1,392", "$ 6,421"),
    )
    caption = ("Changes in Standardized Measure of Discounted Future Net Cash Flows",)
    prose = "Asset retirement obligations are described in Note 9."
    legs = aro_legs(_text(rows, caption=caption, prose=prose), SPEC)
    assert legs["subject2"] and legs["bookend_f2d"] and legs["m1"]
    assert legs["exclusion_x"] and not legs["claim"]
    verdict = _verdict(rows, caption=caption, prose=prose)
    assert not verdict.admitted
    assert "subject exclusion" in verdict.detail


def test_exploratory_subject_refused_by_exclusion():
    rows = (
        ("Balance at beginning of period", "100"),
        ("Accretion", "5"),
        ("Balance at end of period", "105"),
    )
    caption = ("Asset Retirement Obligations — Exploratory Wells",)
    legs = aro_legs(_text(rows, caption=caption), SPEC)
    assert legs["exclusion_x"] and not legs["claim"]


def test_schedule_two_known_touch_admits_as_priced():
    # The specimen's verbatim packet shape (0001111711-24-000011:93):
    # a three-year stacked Schedule II; the ARO subject is prose-only.
    rows = (
        ("Twelve months ended December 31, 2023",),
        ("", "", "", "Additions"),
        (
            "($ in millions)",
            "Balance Jan. 1, 2023",
            "",
            "Charged to Costs and Expenses",
            "",
            "Charged to Other Account (1)",
            "",
            "Deductions for Purposes for which Reserves were Created",
            "",
            "Balance Dec. 31, 2023",
        ),
        (
            "Reserves Deducted in Consolidated Balance Sheet from Assets to Which They Apply:",
        ),
        (
            "Reserve for accounts receivable",
            "$",
            "23.9",
            "$",
            "23.4",
            "$",
            "36.6",
            "$",
            "61.0",
            "$",
            "22.9",
        ),
        (
            "Reserve for deferred charges and other",
            "1.0",
            "",
            "—",
            "",
            "0.3",
            "",
            "—",
            "",
            "1.3",
        ),
        ("",),
        ("Twelve months ended December 31, 2022",),
        ("", "", "", "Additions"),
        (
            "($ in millions)",
            "Balance Jan. 1, 2022",
            "",
            "Charged to Costs and Expenses",
            "",
            "Charged to Other Account (1)",
            "",
            "Deductions for Purposes for which Reserves were Created",
            "",
            "Balance Dec. 31, 2022",
        ),
        (
            "Reserves Deducted in Consolidated Balance Sheet from Assets to Which They Apply:",
        ),
        (
            "Reserve for accounts receivable",
            "$",
            "23.5",
            "$",
            "20.6",
            "$",
            "36.4",
            "$",
            "56.6",
            "$",
            "23.9",
        ),
        (
            "Reserve for deferred charges and other",
            "2.3",
            "",
            "—",
            "",
            "(1.3)",
            "",
            "—",
            "",
            "1.0",
        ),
        ("",),
        ("Twelve months ended December 31, 2021",),
        ("", "", "", "Additions"),
        (
            "($ in millions)",
            "Balance Jan. 1, 2021",
            "",
            "Charged to Costs and Expenses",
            "",
            "Charged to Other Account (1)",
            "",
            "Deductions for Purposes for which Reserves were Created",
            "",
            "Balance Dec. 31, 2021",
        ),
        (
            "Reserves Deducted in Consolidated Balance Sheet from Assets to Which They Apply:",
        ),
        (
            "Reserve for accounts receivable",
            "$",
            "52.3",
            "$",
            "18.3",
            "$",
            "6.4",
            "$",
            "53.5",
            "$",
            "23.5",
        ),
        (
            "Reserve for deferred charges and other",
            "—",
            "",
            "—",
            "",
            "2.3",
            "",
            "—",
            "",
            "2.3",
        ),
    )
    caption = ("Twelve months ended December 31, 2023", "Additions")
    prose = (
        '(1)See Note 12, "Regulatory Matters," for additional information.\n'
        '(2)See Note 11, "Asset Retirement Obligations," for additional '
        "information.\n(3)Represents investing non-cash activity. See Note 4, "
        '"Noncontrolling Interest," for additional information.\n(4)Refer to '
        'Note 6, "Equity," for additional information.\nITEM 8. FINANCIAL '
        "STATEMENTS AND SUPPLEMENTARY DATA (continued)\nSCHEDULE II – "
        "VALUATION AND QUALIFYING ACCOUNTS"
    )
    legs = aro_legs(_text(rows, caption=caption, prose=prose), SPEC)
    assert legs["bookend_f2"] and legs["claim"]
    assert _verdict(rows, caption=caption, prose=prose).admitted


def test_bare_bookend_walk_admits_via_b():
    rows = (
        ("", "2016", "", "", "2015", ""),
        ("Beginning of period", "$", "264,137", "", "$", "287,463"),
        ("Liabilities incurred", "", "2,694", "", "", "4,595"),
        ("Liabilities settled", "", "(11,511)", "", "", "(18,828)"),
        ("End of period", "$", "255,320", "", "$", "264,137"),
    )
    prose = (
        "(9) Asset Retirement Obligations\nOur asset retirement "
        "obligations primarily represent the present value of the "
        "estimated amounts we will incur to plug, abandon and "
        "remediate our producing properties."
    )
    legs = aro_legs(_text(rows, prose=prose), SPEC)
    assert not legs["bookend_f2c"]
    assert legs["bare_bookend"] and legs["claim"]
    assert _verdict(rows, prose=prose).admitted


def test_warranty_admission_stands_as_priced():
    rows = (
        ("", "2017", "", "", "2016", ""),
        ("Beginning of the period", "$", "20,380", "", "$", "21,710"),
        ("Assumed from business acquisition", "1,963", "", "", "—", ""),
        ("Provision", "15,341", "", "", "9,772", ""),
        ("Settlements", "(15,270)", "", "", "(11,339)", ""),
        ("Currency translation", "(503)", "", "", "237", ""),
        ("End of the period", "$", "21,911", "", "$", "20,380"),
    )
    caption = ("Years Ended March 31,",)
    prose = (
        "In connection with its leased facilities, the Company "
        "recognized a liability for asset retirement obligations for "
        "2017 and 2016 representing the present value of estimated "
        "remediation costs to be incurred at lease expiration.\n"
        "Changes in the Company's warranty liability for fiscal years "
        "2017 and 2016 were as follows (in thousands):"
    )
    legs = aro_legs(_text(rows, caption=caption, prose=prose), SPEC)
    assert legs["bare_bookend"] and legs["claim"]


def test_other_subject_walk_refused_at_subject():
    rows = (
        ("Balance at beginning of period", "100"),
        ("Additions", "5"),
        ("Balance at end of period", "105"),
    )
    prose = "The changes in the carrying amount of goodwill are as follows:"
    legs = aro_legs(_text(rows, caption=("Goodwill",), prose=prose), SPEC)
    assert not legs["subject2"]
    assert not legs["claim"]


def test_static_composition_refused():
    rows = (
        ("Current portion", "10"),
        ("Noncurrent portion", "90"),
        ("Total asset retirement obligations", "100"),
    )
    legs = aro_legs(_text(rows, caption=("Asset Retirement Obligations",)), SPEC)
    assert legs["subject_lead"]
    assert not legs["bookend_f2d"]
    assert not legs["claim"]


def test_no_bookend_line_walk_refused():
    rows = (
        ("Accretion expense", "5"),
        ("Liabilities incurred", "10"),
        ("Total", "115"),
    )
    legs = aro_legs(_text(rows, caption=("Asset Retirement Obligations",)), SPEC)
    assert legs["subject_lead"] and legs["m1"]
    assert not legs["bookend_f2e"]
    assert not legs["claim"]


def test_dated_subject_walk_admits_via_d():
    rows = (
        ("Nuclear decommissioning ARO at December 31, 2012(a)", "$", "4,741", ""),
        ("Accretion expense", "", "129", ""),
        ("Costs incurred to decommission retired plants", "", "(2)", ""),
        ("", "", "", ""),
        ("Nuclear decommissioning ARO at June 30, 2013(a)", "$", "4,868", ""),
    )
    prose = (
        "The following table provides a rollforward of the nuclear "
        "decommissioning ARO reflected on Exelon's and Generation's "
        "Consolidated Balance Sheets from December 31, 2012 to "
        "June 30, 2013:"
    )
    legs = aro_legs(_text(rows, prose=prose), SPEC)
    assert not legs["bookend_f2d"]
    assert legs["dated_subject_d"] and not legs["claim_f2d"]
    assert legs["claim"]
    assert _verdict(rows, prose=prose).admitted


def test_dated_rows_without_subject_in_line_refused():
    rows = (
        ("Plant retirement costs at December 31, 2012", "100"),
        ("Accretion expense", "5"),
        ("Plant retirement costs at June 30, 2013", "105"),
    )
    legs = aro_legs(_text(rows, caption=("Asset Retirement Obligations",)), SPEC)
    assert legs["subject_lead"] and legs["m1"]
    assert not legs["dated_subject_d"]
    assert not legs["claim"]


def _geometry(stubs):
    return GeometryText(stubs=stubs)


def _result(*families, groups=()):
    scores = {
        family: FamilyScore(family, 11.0, {"signature": 11.0}, ())
        for family in families
    }
    return CompetitionResult(
        claims=families, contested=families, scores=scores, groups=groups
    )


def test_assignment_removes_aro_on_warranty_coclaim():
    geo = _geometry(("Asset retirement obligations",))
    groups = (
        ClaimGroup(
            "aro_rollforward", 11.0, "claimed", "primary", {"signature": 11.0}, (), 0.0
        ),
        ClaimGroup(
            "warranty", 11.0, "claimed", "primary", {"signature": 11.0}, (), 0.0
        ),
    )
    results = apply_aro_assignment(
        [geo], [_result("aro_rollforward", "warranty", groups=groups)]
    )
    assert "aro_rollforward" not in results[0].claims
    assert "aro_rollforward" not in results[0].contested
    assert "warranty" in results[0].claims
    score = results[0].scores["aro_rollforward"]
    assert score.total == 11.0
    evidence = [item for item in score.evidence if item.channel == "gate"]
    assert len(evidence) == 1
    assert evidence[0].detail == ARO_ASSIGNMENT_SPEC.detail
    assert [group.family for group in results[0].groups] == ["warranty"]


def test_assignment_keeps_aro_only():
    geo = _geometry(("Asset retirement obligations",))
    results = apply_aro_assignment([geo], [_result("aro_rollforward")])
    assert "aro_rollforward" in results[0].claims


def test_assignment_keeps_warranty_only():
    geo = _geometry(("Warranty liability",))
    results = apply_aro_assignment([geo], [_result("warranty")])
    assert "warranty" in results[0].claims


def test_assignment_leaves_unclaimed_geometries():
    geo = _geometry(("Asset retirement obligations",))
    before = [_result("balance_sheet")]
    results = apply_aro_assignment([geo], before)
    assert results == before


def test_assignment_leaves_other_families():
    first = _geometry(("Asset retirement obligations",))
    second = _geometry(("Total assets",))
    results = apply_aro_assignment(
        [first, second],
        [_result("aro_rollforward", "warranty"), _result("balance_sheet")],
    )
    assert "aro_rollforward" not in results[0].claims
    assert "warranty" in results[0].claims
    assert "balance_sheet" in results[1].claims
