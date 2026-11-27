"""Profile registry vocabulary: provenance, strata, kind, seat and test names."""

from __future__ import annotations

PROV_FAMILY_SUPPORT = "verdict:family_support"
PROV_DEMOGRAPHICS = "measurement:demographics_profile"
PROV_EX13 = "census:ex13_exhibit_links"

# Strata are the measurement strata: B is the annual stratum,
# D the quarterly stratum. Profiles carry stratum codes, never
# form names (R5: no hardcoded forms).
STRATUM_ANNUAL = "B"
STRATUM_QUARTERLY = "D"

# R6 is ruled genre-layer only: no family profile declares a
# prose window, so every profile carries this value.
PROSE_WINDOW_NONE = "none"

KIND_FAMILY = "family"
KIND_PROSE_PROFILE = "prose_profile"
KIND_GENRE_SEAT = "genre_seat"

SEAT_SIGNATURE = "signature_competition"
SEAT_ASSEMBLY = "assembly"
SEAT_GEOMETRY_TEXT = "geometry_text"
SEAT_NOTE_TITLE_CONTENT = "note_title_content"
SEAT_PROSE_CAPTURE = "prose_capture"
SEAT_GENRE_REFUSAL = "genre_refusal"
SEAT_REGION_GATED = "region_gated"

PROV_DECLARED_SPECS = "form-tests:declared_specs"
PROV_DERIVATIVES_EVIDENCE = "form-tests:derivatives_evidence"
PROV_PENSION_ANCHOR = "form-tests:pension_anchor"
PROV_PENSION_ROUTED = "form-tests:pension_routed_separator"
PROV_PENSION_COMBINATION = "form-tests:pension_combination_separator"
PROV_STEP2_PRICING = "calibration:step2-v3-pricing"
PROV_STEP3_PRICING = "calibration:step3-v3-pricing"
PROV_CI_STEP6_PRICING = "calibration:ci-step6-population-pricing"
PROV_RESTRUCTURING_PRICING = "calibration:restructuring-seat-pricing"
PROV_ARO_BASE = "measurement:aro-adjudication-base"
PROV_S4_GOODWILL_BASE = "measurement:goodwill-adjudication-base"
PROV_WARRANTY_PRICING = "calibration:warranty-seat-pricing"
PROV_R18_SEAT_PRICING = "calibration:r18-seat-pricing"
PROV_STEP7_PRICING = "step7:discovery-pricing"
PROV_S1_PRICING = "calibration:s1-pricing"
PROV_RULING18_PRICING = "pricing:ruling18-pass"
PROV_S6B_PRICING = "calibration:s6b-pricing"
PROV_S5_SEAT_PRICING = "calibration:s5-seat-pricing"
PROV_STEP8_PRICING = "calibration:step8-pricing"
PROV_BALANCE_SHEET_SEPARATOR = "calibration:balance-sheet-separator-pricing"
PROV_CASH_FLOW_CASCADE = "calibration:cash-flow-cascade-pricing"
PROV_CREDIT_SEPARATOR = "calibration:credit-separator-pricing"
PROV_COREFIN_COMPINCOME = "calibration:corefin-compincome-pricing"
PROV_COMBINED_OPERATIONS_SEPARATOR = "calibration:combined-operations-cascade-pricing"
PROV_EPS_TRANSFER_PRICING = "calibration:eps-transfer-pricing"
PROV_EPS_REFUSAL_PRICING = "calibration:eps-refusal-pricing"
PROV_COREFIN_EQUITYSTATEMENT = "calibration:corefin-equitystatement-pricing"
PROV_STOCK_COMP_SEPARATOR = "calibration:stock-comp-cascade-pricing"
PROV_RESTRUCTURING_SEPARATOR = "calibration:rollforward-restructuring-pricing"
PROV_TAX_RECONCILIATION_SEPARATOR = "calibration:tax-reconciliation-separator-pricing"
PROV_DEFERRED_TAX_SEPARATOR = "calibration:deferred-tax-separator-pricing"
PROV_LEASE_SEPARATOR = "calibration:lease-separator-pricing"
PROV_GOODWILL_SEPARATOR = "calibration:goodwill-separator-pricing"
PROV_GOODWILL_FOREIGN_SEPARATOR = "calibration:goodwill-foreign-separator-pricing"
PROV_GOODWILL_SIBLING_SEPARATOR = "calibration:goodwill-sibling-separator-pricing"
PROV_RELATED_PARTY_FORM_SEPARATION = "calibration:related-party-form-separation-pricing"
PROV_CASCADE_G4_FORM_SEPARATION = "calibration:cascade-g4-form-separation-pricing"
PROV_SEAT_FLOOR_PRICING = "calibration:seat-at-floor-claim-path"

# Form-test declarations (R1): names only, as registry data.
# The test classes themselves are implemented outside the
# registry; only their names are data here.
TEST_WALK = "beginning_ending_walk"
TEST_LADDER = "year_ladder"
TEST_PERCENTAGE_FORM = "percentage_form"
TEST_PRIMARY_STATEMENT_SEAT = "primary_statement_seat"
TEST_COMPOSITION_TWIN = "composition_twin"
TEST_SEGMENT_FORM = "segment_form"
TEST_DERIVATIVES_EVIDENCE = "derivatives_evidence_gate"
TEST_ARO_EVIDENCE = "aro_evidence_gate"
TEST_ROW_BOUND = "row_bound"
TEST_SIGNATURE_ABSENCE = "signature_absence"
TEST_PLACEMENT_CONSISTENCY = "placement_consistency"
TEST_MEASURE_SET = "measure_set"
TEST_EPS_EVIDENCE = "eps_evidence"
TEST_EPS_DETECTOR = "eps_detector"
TEST_EPS_ADJACENCY_REFUSAL = "eps_adjacency_refusal"
TEST_EPS_PROFORMA_REFUSAL = "eps_proforma_refusal"
TEST_PPE_EVIDENCE = "ppe_evidence"
TEST_RESTRUCTURING_EVIDENCE = "restructuring_evidence_gate"
TEST_WARRANTY_EVIDENCE = "warranty_evidence_gate"
TEST_INVENTORY_EVIDENCE = "inventory_evidence"
TEST_ADMISSION_EVIDENCE = "admission_evidence"
TEST_LEASE_EVIDENCE = "lease_evidence"
TEST_TAX_EVIDENCE = "tax_evidence_seat"
TEST_STOCK_COMP_EVIDENCE = "stock_comp_evidence"
TEST_LABOR_FORM = "labor_form"
TEST_CREDIT_LOSSES_EVIDENCE = "credit_losses_evidence"
TEST_CORE_FORM = "core_form"
TEST_INTANGIBLES_IDENTITY = "intangibles_identity"
TEST_BALANCE_SHEET_SEPARATOR = "balance_sheet_separator"
TEST_COMPREHENSIVE_INCOME_SEPARATOR = "comprehensive_income_separator"
TEST_PENSION_ROUTED = "pension_routed"
TEST_PENSION_COMBINATION = "pension_combination"
TEST_CASH_FLOW_SEPARATOR = "cash_flow_separator"
TEST_CREDIT_SEPARATOR = "credit_separator"
TEST_EQUITY_SEPARATOR = "equity_separator"
TEST_COMBINED_OPERATIONS_SEPARATOR = "combined_operations_separator"
TEST_STOCK_COMP_SEPARATOR = "stock_comp_separator"
TEST_RESTRUCTURING_SEPARATOR = "restructuring_separator"
TEST_TAX_RECONCILIATION_SEPARATOR = "tax_reconciliation_separator"
TEST_DEFERRED_TAX_SEPARATOR = "deferred_tax_separator"
TEST_LEASE_SEPARATOR = "lease_separator"
TEST_GOODWILL_SEPARATOR = "goodwill_separator"
TEST_GOODWILL_FOREIGN_SEPARATOR = "goodwill_foreign_separator"
TEST_GOODWILL_SIBLING_SEPARATOR = "goodwill_sibling_separator"
TEST_FORM_SEPARATION = "form_separation"
FORM_TESTS = (
    TEST_WALK,
    TEST_LADDER,
    TEST_PERCENTAGE_FORM,
    TEST_PRIMARY_STATEMENT_SEAT,
    TEST_COMPOSITION_TWIN,
    TEST_SEGMENT_FORM,
    TEST_DERIVATIVES_EVIDENCE,
    TEST_ARO_EVIDENCE,
    TEST_ROW_BOUND,
    TEST_SIGNATURE_ABSENCE,
    TEST_PLACEMENT_CONSISTENCY,
    TEST_MEASURE_SET,
    TEST_EPS_EVIDENCE,
    TEST_RESTRUCTURING_EVIDENCE,
    TEST_WARRANTY_EVIDENCE,
    TEST_INVENTORY_EVIDENCE,
    TEST_ADMISSION_EVIDENCE,
    TEST_LEASE_EVIDENCE,
    TEST_TAX_EVIDENCE,
    TEST_STOCK_COMP_EVIDENCE,
    TEST_PPE_EVIDENCE,
    TEST_LABOR_FORM,
    TEST_CREDIT_LOSSES_EVIDENCE,
    TEST_CORE_FORM,
    TEST_INTANGIBLES_IDENTITY,
    TEST_BALANCE_SHEET_SEPARATOR,
    TEST_PENSION_ROUTED,
    TEST_PENSION_COMBINATION,
    TEST_COMPREHENSIVE_INCOME_SEPARATOR,
    TEST_COMBINED_OPERATIONS_SEPARATOR,
    TEST_EPS_DETECTOR,
    TEST_EPS_ADJACENCY_REFUSAL,
    TEST_EPS_PROFORMA_REFUSAL,
    TEST_CASH_FLOW_SEPARATOR,
    TEST_CREDIT_SEPARATOR,
    TEST_EQUITY_SEPARATOR,
    TEST_STOCK_COMP_SEPARATOR,
    TEST_RESTRUCTURING_SEPARATOR,
    TEST_TAX_RECONCILIATION_SEPARATOR,
    TEST_DEFERRED_TAX_SEPARATOR,
    TEST_LEASE_SEPARATOR,
    TEST_GOODWILL_SEPARATOR,
    TEST_GOODWILL_FOREIGN_SEPARATOR,
    TEST_GOODWILL_SIBLING_SEPARATOR,
    TEST_FORM_SEPARATION,
)
