"""Form separation: declaration as form-test data and surfaces."""

from __future__ import annotations

import edgar_sec.engine.tables.extraction.evidence.form.form_separation_evidence as _fse
from edgar_sec.engine.tables.extraction.evidence.form.form_separation_evidence import (
    FormSeparationText,
    evaluate_form_separation,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_specs import (
    FORM_TEST_SPECS,
)
from edgar_sec.engine.tables.extraction.pension.pension_routed_evidence import (
    header_keys as _PENSION_HEADER_KEYS,
    stub_key as _PENSION_STUB_KEY,
)
from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    PROV_CASCADE_G4_FORM_SEPARATION,
    PROV_RELATED_PARTY_FORM_SEPARATION,
    TEST_FORM_SEPARATION,
)
from edgar_sec.engine.tables.extraction.core.subjects.profiles import (
    profile_for,
)

from .form_separation_fixtures import SPEC, _eval


def test_kind_is_declared_as_form_test_data():
    entry = next(
        s
        for s in FORM_TEST_SPECS
        if s.family == "related_party" and s.kind == TEST_FORM_SEPARATION
    )
    assert entry.test_id == "related_party_form_separation"
    assert entry.points == 0.0
    assert entry.provenance == PROV_RELATED_PARTY_FORM_SEPARATION
    assert SPEC.family == "related_party"
    assert TEST_FORM_SEPARATION in profile_for("related_party").form_tests


def test_eps_and_intangibles_are_declared_as_form_test_data():
    for family, test_id in (
        ("eps_reconciliation", "eps_reconciliation_form_separation"),
        ("intangibles", "intangibles_form_separation"),
    ):
        entry = next(
            s
            for s in FORM_TEST_SPECS
            if s.family == family and s.kind == TEST_FORM_SEPARATION
        )
        assert entry.test_id == test_id
        assert entry.points == 0.0
        assert entry.provenance == PROV_CASCADE_G4_FORM_SEPARATION
        assert TEST_FORM_SEPARATION in profile_for(family).form_tests


def test_packet_and_rows_surfaces_agree():
    rows = (
        ("Due from related parties", "10"),
        ("Due to related parties", "50"),
    )
    via_rows = evaluate_form_separation(FormSeparationText.from_rows(rows), SPEC)
    via_packet = evaluate_form_separation(
        FormSeparationText.from_packet(
            {
                "table_text": (
                    "Due from related parties | 10\nDue to related parties | 50"
                )
            }
        ),
        SPEC,
    )
    assert via_rows == via_packet


def test_recognizer_homes():
    assert _fse.stub_key is _PENSION_STUB_KEY
    assert _fse.header_keys is _PENSION_HEADER_KEYS


def test_empty_grid_is_unevaluable():
    verdict = _eval("")
    assert not verdict.fired
    assert not verdict.evaluable
