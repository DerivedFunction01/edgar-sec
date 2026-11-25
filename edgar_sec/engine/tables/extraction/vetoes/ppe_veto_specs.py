"""PPE veto composition: the priced data.

The census-arbitrated strong stub keys, the leg thresholds,
and the channel sets the veto pass prices.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.core.subjects.signature_profiles import (
    CHANNELS as SIGNATURE_CHANNELS,
)

PPE_FAMILY = "ppe"

# Leg names, in the order the gate note reports them.
LEG_HOST_CLAIM = "H2claim"
LEG_DOMINANCE = "LBdomF"
LEG_LEAD_BALANCE = "L6bal0.4"
LEG_CONTEXT_CARRIED = "D1c_true"
LEG_WEAK_SIGNATURE = "B6sig5div1"
LEG_COEX_LEAD = "AcoexLead"
LEG_STATEMENT_FORM = "Bstmt30x100"

HOST_MIN_SHARED_KEYS = 2
LEAD_BALANCE_MIN = 0.4
WEAK_SIG_MAX = 5.0
WEAK_CLASS_DIVERSITY_MAX = 1
STATEMENT_MIN_DATA_ROWS = 30
STATEMENT_MIN_NUMERIC_CELLS = 100

# The veto-override seat (recall pricing): the hard term
# a seat may override, its signature floor, and the
# form-test pair marking a form-test admission seat.
OVSEAT_TERM = "acquisition"
OVSEAT_SIG_FLOOR = 5.0
ADMISSION_FORM_TEST_DETAILS = ("ppe_evidence passed", "ppe_row_bound passed")

# The discipline seat (Leg D, enlarged-set pricing): the
# class-diversity and numeric floors of the family's
# discipline form, and its Schedule III numeric floor.
DISCIPLINE_CLASS_MIN = 2
DISCIPLINE_NUMERIC_MIN = 2
DISCIPLINE_S3_NUMERIC_MIN = 3

# PPE asset-class terms: a geometry's class diversity is
# the count of these terms its normalized stubs carry.
CLASS_TERMS = (
    "land",
    "building",
    "machinery",
    "equipment",
    "furniture",
    "vehicle",
    "leasehold",
    "construction in progress",
    "computer",
    "fixtures",
    "improvements",
    "capitalized",
)

PROSE_CHANNELS = ("leadin", "lead_title", "caption", "notehead")

# Census-arbitrated strong stub keys by family (derivation
# pop/pop/norm/pop), carried verbatim as population
# constants: each family's census-strong normalized stubs.
STRONG_STUB_KEYS: dict[str, frozenset[str]] = {
    "aro_rollforward": frozenset({"accretion expense"}),
    "balance_sheet": frozenset(
        {
            "assets",
            "cash and cash equivalents",
            "current assets",
            "current liabilities",
            "total assets",
            "total current assets",
            "total current liabilities",
            "total liabilities",
        }
    ),
    "cash_flow": frozenset(
        {
            "cash flows from financing activities",
            "cash flows from investing activities",
        }
    ),
    "combined_operations_ci": frozenset({"operating expenses"}),
    "lease_maturity": frozenset({"thereafter"}),
    "credit_losses_rollforward": frozenset({"recoveries"}),
    "warrant_activity": frozenset({"exercised", "issued"}),
    "inventory": frozenset({"finished goods", "raw materials"}),
    "valuation_model_assumptions": frozenset({"expected volatility"}),
    "shares_purchased": frozenset({"period", "total"}),
    "stock_comp_rollforward": frozenset({"granted"}),
}
