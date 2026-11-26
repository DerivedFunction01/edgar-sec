"""EPS formation seat: the priced leg data.

Leg floors, the form tests each leg reads, the candidate
anatomy terms, and the guard's own refusal forms.
"""

from __future__ import annotations

FAMILY = "eps_reconciliation"

# Leg A (dominance): eps is the top score over this floor
# and every admission form test passed.
LEG_A_FLOOR = 15.0

# Leg B (lead-named): eps clears this floor and the lead
# names the basic-and-diluted calculation.
LEG_B_FLOOR = 40.0
LEG_B_LEAD_PHRASES = ("basic and diluted", "calculation")

# The admission form tests, by test id: leg A reads all
# four, leg B the evidence and detector pair.
EVIDENCE_TEST = "eps_evidence"
DETECTOR_TEST = "eps_detector"
PROFORMA_REFUSAL_TEST = "eps_proforma_refusal"
FORM_SEPARATION_TEST = "eps_reconciliation_form_separation"
LEG_A_FORM_TESTS = (
    EVIDENCE_TEST,
    DETECTOR_TEST,
    PROFORMA_REFUSAL_TEST,
    FORM_SEPARATION_TEST,
)
LEG_B_FORM_TESTS = (EVIDENCE_TEST, DETECTOR_TEST)

# Candidate anatomy: both share bases in the grid, plus an
# anatomy term in stub/grid or a per-share lead term.
CANDIDATE_GRID_TERMS = ("basic", "diluted")
CANDIDATE_ANATOMY_TERMS = (
    "per share",
    "weighted average",
    "denominator",
    "numerator",
    "dilutive",
    "earnings per share",
    "income per share",
    "loss per share",
)
CANDIDATE_LEAD_TERMS = ("earnings per share", "per share")

# Guard forms beyond the registered eps precision legs:
# the restatement-note low-score form and the walk-failed
# low-score form, priced as seat refusals.
GUARD_RESTATEMENT_TERM = "restatement"
GUARD_RESTATEMENT_FLOOR = 20.0
GUARD_WALK_FLOOR = 10.0
WALK_TEST = "eps_numerator_denominator_walk"
