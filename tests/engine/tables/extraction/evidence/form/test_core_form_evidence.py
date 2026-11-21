"""Core-form evidence (TEST_CORE_FORM): registry, components, gate."""

from __future__ import annotations

import pathlib

import edgar_sec.engine.tables.extraction.evidence.form.core_form_evidence as _cfe
from edgar_sec.engine.tables.ascii_html.model.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.cascade.competition import compete
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.core.text.context import TableContext
from edgar_sec.engine.tables.extraction.evidence.form.core_form_evidence import (
    CoreFormText,
    evaluate_core_form,
    evaluate_form_test_core_form,
    norml,
)
from edgar_sec.engine.tables.extraction.form_specs.core_form_specs import (
    CORE_FORM_SPECS,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_specs import (
    FORM_TEST_SPECS,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_types import (
    FormTestOutcome,
)
from edgar_sec.engine.tables.extraction.form_tests.form_tests import evaluate_form_tests
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    FamilyScore,
)
from edgar_sec.engine.tables.extraction.core.subjects.profiles import (
    PROV_STEP8_PRICING,
    TEST_CORE_FORM,
    profile_for,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table
from edgar_sec.engine.tables.numeric_cells import (
    STRICT_NUMERIC_CELL_RE as _HOME_STRICT,
)
from edgar_sec.foundation.text.dates import (
    NUMERIC_DATE_RE as _HOME_NUMERIC_DATE,
)
from edgar_sec.foundation.text.dates import (
    RE_FULL_DATE as _HOME_FULL_DATE,
)
from edgar_sec.foundation.text.dates import (
    STRICT_MONTH_PATTERN as _HOME_STRICT_MONTH,
)
from edgar_sec.foundation.text.dates import (
    YEAR_TOKEN_RE as _HOME_YEAR_TOKEN,
)
from edgar_sec.foundation.text.patterns import (
    RE_WHITESPACE as _HOME_WHITESPACE,
)

FAMILIES = ("intangibles", "fair_value", "segment_reporting")


def _letters(verdict) -> str:
    detail = verdict.detail
    assert detail.startswith("core form: ")
    return detail[len("core form: ") :].split(" ")[0]


def _eval(family: str, table_text: str, prose: str = ""):
    text = CoreFormText(table_text, (), prose)
    return evaluate_core_form(text, CORE_FORM_SPECS[family])


def test_kind_is_declared_as_form_test_data():
    for family in FAMILIES:
        entry = next(
            s
            for s in FORM_TEST_SPECS
            if s.family == family and s.kind == TEST_CORE_FORM
        )
        assert entry.points == 3.0
        assert entry.provenance == PROV_STEP8_PRICING
        assert CORE_FORM_SPECS[family].family == family
        assert TEST_CORE_FORM in profile_for(family).form_tests


def test_norml_is_the_frozen_norm():
    assert norml("  Gross\t Carrying\nAmount ") == "gross carrying amount"
    assert norml("") == "" and norml(None) == ""


def test_packet_and_rows_surfaces_agree():
    rows = (
        ("Customer relationships", "100"),
        ("Accumulated amortization", "(30)"),
    )
    via_rows = evaluate_core_form(
        CoreFormText.from_rows(rows, ("Intangibles",), "See the note."),
        CORE_FORM_SPECS["intangibles"],
    )
    via_packet = evaluate_core_form(
        CoreFormText.from_packet(
            {
                "table_text": (
                    "Customer relationships | 100\nAccumulated amortization | (30)"
                ),
                "caption_stack": ["Intangibles"],
                "prose_before": "See the note.",
            }
        ),
        CORE_FORM_SPECS["intangibles"],
    )
    assert via_rows == via_packet


# ---------------- intangibles components ----------------


def test_intangibles_a_and_e_from_class_stubs():
    verdict = _eval(
        "intangibles",
        "Customer relationships | 100\n"
        "Trade names | 50\n"
        "Accumulated amortization | (30)",
    )
    assert verdict.core_present
    assert "A" in _letters(verdict) and "E" in _letters(verdict)


def test_intangibles_b_gross_net_form():
    verdict = _eval(
        "intangibles",
        "Gross carrying amount | 100\nAccumulated amortization | (30)\nNet | 70",
    )
    assert _letters(verdict) == "B"


def test_intangibles_c_year_rows():
    verdict = _eval(
        "intangibles",
        "2021 | 10\n2022 | 20\n2023 | 30\nAmortization expense | 5",
    )
    assert _letters(verdict) == "C"


def test_intangibles_d_goodwill_in_prose():
    verdict = _eval(
        "intangibles",
        "Balance at January 1 | 100\nOther | 3",
        prose="The carrying amount of goodwill was recorded.",
    )
    assert "D" in _letters(verdict)


def test_intangibles_f_plural_useful_lives():
    verdict = _eval(
        "intangibles",
        "Patents | 100\nLicenses | 50\nWeighted average | Useful Lives",
    )
    assert _letters(verdict) == "F"


def test_intangibles_g_accum_and_balance_stubs():
    verdict = _eval(
        "intangibles",
        "Accumulated amortization | (30)\nBalance | 70",
    )
    assert _letters(verdict) == "G"


def test_intangibles_no_core_form():
    verdict = _eval("intangibles", "Revenue | 100\nCost of sales | 60")
    assert not verdict.core_present
    assert verdict.detail.startswith("core form: - ")


# ---------------- fair_value components ----------------


def test_fair_value_a_two_levels():
    verdict = _eval("fair_value", "Cash | Level 1 | 100\nBonds | Level 2 | 200")
    assert _letters(verdict) == "A"


def test_fair_value_b_level3_beginning_stub():
    verdict = _eval(
        "fair_value",
        "Beginning balance | 100\nPurchases | 20\nLevel 3 assets | 120",
    )
    assert _letters(verdict) == "B"


def test_fair_value_c_only_carries_the_named_gap():
    verdict = _eval(
        "fair_value",
        "Fair Value Measurements | \n"
        "Cash equivalents | 100\n"
        "Marketable securities | 200\n"
        "Corporate bonds | 300",
    )
    assert verdict.core_present
    assert _letters(verdict) == "C"
    assert verdict.detail.endswith("c-only named gap")


def test_fair_value_no_core_form():
    verdict = _eval("fair_value", "Revenue | 100\nExpenses | 40")
    assert not verdict.core_present


# ---------------- segment components ----------------


def test_segment_members_from_columns():
    verdict = _eval(
        "segment_reporting",
        " | North America | Europe\nRevenue | 100 | 200",
    )
    assert verdict.core_present
    assert "members=2" in verdict.detail


def test_segment_stubn_counts_pre_numeric_date_row():
    verdict = _eval(
        "segment_reporting",
        "Operating Segments | June 29, 2014\nProduct A | 10\nProduct B sales | 20",
    )
    assert verdict.core_present
    assert "stubn=3" in verdict.detail


def test_segment_stoplist_holds_members_below_two():
    verdict = _eval(
        "segment_reporting",
        " | Net income | Europe\nRevenue | 100 | 200",
    )
    assert not verdict.core_present
    assert "members=1" in verdict.detail


def test_segment_no_core_form():
    verdict = _eval("segment_reporting", "Total | 100")
    assert not verdict.core_present


# ---------------- F-S8-2 census dispositions ----------------


def test_cured_recognizers_consume_their_homes():
    assert _cfe.STRICT_NUMERIC_CELL_RE is _HOME_STRICT
    assert _cfe.RE_WHITESPACE is _HOME_WHITESPACE
    assert _cfe.DATE_RES[0] is _HOME_NUMERIC_DATE
    assert _cfe.DATE_RES[1] is _HOME_YEAR_TOKEN
    assert _cfe.FULLDATE_RES[0] is _HOME_NUMERIC_DATE
    assert _cfe.FULLDATE_RES[1] is _HOME_FULL_DATE


def test_no_cured_private_literal_remains_in_the_module():
    source = pathlib.Path(_cfe.__file__).read_text(encoding="utf-8")
    for literal in (
        r"^\$?\(?\d[\d,]*(\.\d+)?\)?\%?$",
        r"^\d{4}$",
        r"\b(?:19|20)\d{2}\b",
        r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    ):
        assert literal not in source


def test_month_dialect_is_the_strict_home_token():
    assert _cfe.STRICT_MONTH_PATTERN is _HOME_STRICT_MONTH
    month_day = _cfe.DATE_RES[2]
    assert month_day.search("december 31")
    assert not month_day.search("dec. 31")
    month_year = _cfe.DATE_RES[4]
    assert month_year.search("december 2024")
    assert not month_year.search("december 1800")


def test_units_stub_language_survives_its_vocabulary_rehome():
    assert _cfe.UNITS_STUB_RE.match("($ in millions)")
    assert _cfe.UNITS_STUB_RE.match("(millions)")
    assert not _cfe.UNITS_STUB_RE.match("revenue")


def test_home_of_record_recognizers_keep_their_frozen_text():
    expected = {
        "LEVEL_RE": r"level ([123])\b",
        "USEFUL_LIFE_RE": r"useful li(?:fe|ves)",
        "NET_WORD_RE": r"\bnet\b",
        "FOOTNOTE_TAIL_RE": r"\(\d+\)$",
        "MARKER_ONLY_RE": r"^(\([a-z0-9]{1,2}\))+$",
        "FULL_PAREN_RE": r"^\(.*\)$",
        "TRAILING_PAREN_RE": r"\s*\([^()]*\)$",
        "LETTER_RE": r"[a-z]",
    }
    for name, pattern in expected.items():
        assert getattr(_cfe, name).pattern == pattern


# ---------------- stage adapter + dispatch ----------------


def _table(rows, prose_before="", caption_stack=()):
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
        geometry=geometry,
        caption_stack=caption_stack,
        prose_before=prose_before,
    )
    return structure_table(context)


def test_stage_adapter_over_full_grid():
    table = _table(
        (
            ("Customer relationships", "100"),
            ("Trade names", "50"),
            ("Accumulated amortization", "(30)"),
        )
    )
    spec = next(s for s in FORM_TEST_SPECS if s.test_id == "intangibles_core_form")
    verdict = evaluate_form_test_core_form(table, spec)
    assert verdict.core_present
    assert "A" in _letters(verdict)


def test_stage_dispatch_stamps_core_form_outcome():
    table = _table(
        (
            ("Customer relationships", "100"),
            ("Trade names", "50"),
            ("Accumulated amortization", "(30)"),
        )
    )
    outcomes = {o.test_id: o for o in evaluate_form_tests(table)}
    outcome = outcomes["intangibles_core_form"]
    assert outcome.kind == TEST_CORE_FORM
    assert outcome.passed and outcome.evaluable
    assert outcome.points == 3.0


# ---------------- competition gate ----------------

_SCORE = {"intangibles": FamilyScore("intangibles", 11.0, {"signature": 11.0}, ())}


def _outcome(passed: bool, evaluable: bool = True) -> FormTestOutcome:
    return FormTestOutcome(
        "intangibles",
        "intangibles_core_form",
        TEST_CORE_FORM,
        passed,
        evaluable,
        0,
        3.0,
        "core form: - (nclass=0 yearrows=0)",
    )


def test_gate_removes_claim_on_failed_outcome():
    geometry = GeometryText(form_tests=(_outcome(False),))
    result = compete(geometry, scores=dict(_SCORE))
    assert "intangibles" not in result.claims
    evidence = result.scores["intangibles"].evidence
    assert any(
        item.channel == "gate" and "core form" in item.detail for item in evidence
    )


def test_gate_keeps_claim_on_passed_outcome():
    geometry = GeometryText(form_tests=(_outcome(True),))
    result = compete(geometry, scores=dict(_SCORE))
    assert "intangibles" in result.claims


def test_gate_keeps_claim_when_outcome_absent():
    result = compete(GeometryText(), scores=dict(_SCORE))
    assert "intangibles" in result.claims


def test_gate_keeps_claim_when_outcome_unevaluable():
    geometry = GeometryText(form_tests=(_outcome(False, evaluable=False),))
    result = compete(geometry, scores=dict(_SCORE))
    assert "intangibles" in result.claims
