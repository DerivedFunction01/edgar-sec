"""Form-test entries: composition twins, per-family evidence
gates, and core forms — the note-family block of the registry,
composed into FORM_TEST_SPECS by form_test_specs.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.form_specs.form_test_types import FormTestSpec
from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    PROV_DEFERRED_TAX_SEPARATOR,
    PROV_DERIVATIVES_EVIDENCE,
    PROV_R18_SEAT_PRICING,
    PROV_STEP8_PRICING,
    TEST_COMPOSITION_TWIN,
    TEST_CORE_FORM,
    TEST_DEFERRED_TAX_SEPARATOR,
    TEST_DERIVATIVES_EVIDENCE,
    TEST_INVENTORY_EVIDENCE,
    TEST_LEASE_EVIDENCE,
    TEST_PPE_EVIDENCE,
)

COMPOSITION_FORM_TEST_ENTRIES: tuple[FormTestSpec, ...] = (
    FormTestSpec("pension", TEST_COMPOSITION_TWIN, "pension_composition", 3.0),
    FormTestSpec("ppe", TEST_COMPOSITION_TWIN, "ppe_composition", 3.0),
    FormTestSpec(
        "ppe",
        TEST_PPE_EVIDENCE,
        "ppe_evidence",
        3.0,
        provenance=PROV_R18_SEAT_PRICING,
    ),
    FormTestSpec("intangibles", TEST_COMPOSITION_TWIN, "intangibles_composition", 3.0),
    FormTestSpec(
        "deferred_tax", TEST_COMPOSITION_TWIN, "deferred_tax_composition", 3.0
    ),
    FormTestSpec(
        "deferred_tax",
        TEST_DEFERRED_TAX_SEPARATOR,
        "deferred_tax_separator",
        0.0,
        provenance=PROV_DEFERRED_TAX_SEPARATOR,
    ),
    FormTestSpec("inventory", TEST_COMPOSITION_TWIN, "inventory_composition", 3.0),
    FormTestSpec(
        "inventory",
        TEST_INVENTORY_EVIDENCE,
        "inventory_evidence",
        3.0,
        provenance=PROV_R18_SEAT_PRICING,
    ),
    FormTestSpec(
        "lease_maturity", TEST_COMPOSITION_TWIN, "lease_maturity_composition", 3.0
    ),
    FormTestSpec(
        "lease_maturity",
        TEST_LEASE_EVIDENCE,
        "lease_evidence",
        3.0,
        provenance=PROV_R18_SEAT_PRICING,
    ),
    FormTestSpec("fair_value", TEST_COMPOSITION_TWIN, "fair_value_composition", 3.0),
    FormTestSpec(
        "derivatives_hedging",
        TEST_DERIVATIVES_EVIDENCE,
        "derivatives_hedging_evidence_gate",
        0.0,
        provenance=PROV_DERIVATIVES_EVIDENCE,
    ),
    FormTestSpec(
        "intangibles",
        TEST_CORE_FORM,
        "intangibles_core_form",
        3.0,
        provenance=PROV_STEP8_PRICING,
    ),
    FormTestSpec(
        "fair_value",
        TEST_CORE_FORM,
        "fair_value_core_form",
        3.0,
        provenance=PROV_STEP8_PRICING,
    ),
    FormTestSpec(
        "segment_reporting",
        TEST_CORE_FORM,
        "segment_reporting_core_form",
        3.0,
        provenance=PROV_STEP8_PRICING,
    ),
)
