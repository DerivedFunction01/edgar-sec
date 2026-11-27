"""Stamped-outcome gates: the priced separator and detector
outcomes that refuse a family's claim when they fired.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.separators.balance_sheet_separator_evidence import (
    fired_separator_outcome,
)
from edgar_sec.engine.tables.extraction.separators.cash_flow_separator_evidence import (
    fired_separator_outcome as fired_cash_flow_separator_outcome,
)
from edgar_sec.engine.tables.extraction.evidence.form.core_form_evidence import (
    failing_core_form_outcome,
)
from edgar_sec.engine.tables.extraction.note_separators.credit_separator_evidence import (
    fired_separator_outcome as fired_credit_separator_outcome,
)
from edgar_sec.engine.tables.extraction.note_separators.deferred_tax_separator_evidence import (
    fired_separator_outcome as fired_deferred_tax_separator_outcome,
)
from edgar_sec.engine.tables.extraction.note_separators.lease_separator_evidence import (
    fired_separator_outcome as fired_lease_separator_outcome,
)
from edgar_sec.engine.tables.extraction.note_separators.goodwill_separator_evidence import (
    fired_separator_outcome as fired_goodwill_separator_outcome,
)
from edgar_sec.engine.tables.extraction.note_separators.goodwill_foreign_separator_evidence import (
    fired_separator_outcome as fired_goodwill_foreign_separator_outcome,
)
from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    TEST_BALANCE_SHEET_SEPARATOR,
    TEST_CASH_FLOW_SEPARATOR,
    TEST_COMPREHENSIVE_INCOME_SEPARATOR,
    TEST_CREDIT_SEPARATOR,
    TEST_DEFERRED_TAX_SEPARATOR,
    TEST_EPS_DETECTOR,
    TEST_EPS_ADJACENCY_REFUSAL,
    TEST_EPS_PROFORMA_REFUSAL,
    TEST_EQUITY_SEPARATOR,
    TEST_FORM_SEPARATION,
    TEST_GOODWILL_FOREIGN_SEPARATOR,
    TEST_GOODWILL_SEPARATOR,
    TEST_LEASE_SEPARATOR,
    TEST_RESTRUCTURING_SEPARATOR,
    TEST_STOCK_COMP_SEPARATOR,
    TEST_TAX_RECONCILIATION_SEPARATOR,
)
from edgar_sec.engine.tables.extraction.cascade.scoring.score_trail import append_note
from edgar_sec.engine.tables.extraction.note_separators.stock_comp_separator_evidence import (
    fired_separator_outcome as fired_stock_comp_separator_outcome,
)
from edgar_sec.engine.tables.extraction.note_separators.tax_reconciliation_separator_evidence import (
    fired_separator_outcome as fired_tax_reconciliation_separator_outcome,
)


# Stamped-outcome gates (priced): a claim is refused when its
# family's stamped outcome fired; an absent or unevaluable
# outcome never fails the gate.
STAMPED_GATES = (
    ("balance_sheet", TEST_BALANCE_SHEET_SEPARATOR, fired_separator_outcome),
    ("cash_flow", TEST_CASH_FLOW_SEPARATOR, fired_cash_flow_separator_outcome),
    (
        "credit_losses_rollforward",
        TEST_CREDIT_SEPARATOR,
        fired_credit_separator_outcome,
    ),
    ("eps_reconciliation", TEST_EPS_DETECTOR, failing_core_form_outcome),
    ("eps_reconciliation", TEST_EPS_ADJACENCY_REFUSAL, failing_core_form_outcome),
    ("eps_reconciliation", TEST_EPS_PROFORMA_REFUSAL, failing_core_form_outcome),
    ("eps_reconciliation", TEST_FORM_SEPARATION, failing_core_form_outcome),
    ("intangibles", TEST_FORM_SEPARATION, failing_core_form_outcome),
    (
        "comprehensive_income",
        TEST_COMPREHENSIVE_INCOME_SEPARATOR,
        fired_separator_outcome,
    ),
    ("equity_statement", TEST_EQUITY_SEPARATOR, fired_separator_outcome),
    (
        "stock_comp_rollforward",
        TEST_STOCK_COMP_SEPARATOR,
        fired_stock_comp_separator_outcome,
    ),
    ("restructuring", TEST_RESTRUCTURING_SEPARATOR, fired_separator_outcome),
    ("related_party", TEST_FORM_SEPARATION, failing_core_form_outcome),
    (
        "tax_reconciliation",
        TEST_TAX_RECONCILIATION_SEPARATOR,
        fired_tax_reconciliation_separator_outcome,
    ),
    (
        "deferred_tax",
        TEST_DEFERRED_TAX_SEPARATOR,
        fired_deferred_tax_separator_outcome,
    ),
    ("lease_maturity", TEST_LEASE_SEPARATOR, fired_lease_separator_outcome),
    (
        "goodwill_rollforward",
        TEST_GOODWILL_SEPARATOR,
        fired_goodwill_separator_outcome,
    ),
    (
        "goodwill_rollforward",
        TEST_GOODWILL_FOREIGN_SEPARATOR,
        fired_goodwill_foreign_separator_outcome,
    ),
)


# Form-conditioned stamped-gate exemptions (greenfield
# intangibles packet): the named gate does not refuse the
# family's claim when a companion form test passed.
STAMPED_GATE_FORM_EXEMPTIONS = {
    ("intangibles", TEST_FORM_SEPARATION): ("intangibles_identity_form",),
}


def apply_stamped_gates(claims, contested, scores, geometry):
    """Refuse claims whose stamped gate outcome fired."""
    for family, test_id, outcome_of in STAMPED_GATES:
        if family not in claims:
            continue
        fired = outcome_of(geometry.form_tests, family, test_id)
        if fired is None:
            continue
        companions = STAMPED_GATE_FORM_EXEMPTIONS.get((family, test_id))
        if companions is not None and any(
            o.test_id in companions and o.passed for o in geometry.form_tests
        ):
            continue
        claims.remove(family)
        if family in contested:
            contested.remove(family)
        scores = append_note(scores, family, "gate", fired.detail)
    return scores
