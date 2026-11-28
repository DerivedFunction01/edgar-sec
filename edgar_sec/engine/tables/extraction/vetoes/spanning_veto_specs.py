"""Spanning veto compositions: the priced data.

The Round-3 P1 packet thresholds: the cash_flow dominance
ratio and the balance_sheet filing-relative floor.
"""

from __future__ import annotations

CF_FAMILY = "cash_flow"
BS_FAMILY = "balance_sheet"

# Leg names, in the order the gate note reports them.
LEG_CF_DOMINANCE = "dominance"
LEG_CF_SIGNATURE = "signature"
LEG_CF_CONTEXT = "context"
LEG_BS_FILING_RELATIVE = "filing-relative"

# CF-1: a cash_flow claim seats only at >= 1.25x the
# geometry's best rival-family score — the production
# DOMINANCE_RATIO restated as a seating requirement.
CF_DOMINANCE_RATIO = 1.25

# CF-2: a cash_flow claim seats only when its signature-absence
# form test passes (one stamped test: cash_flow_signature_absence);
# the unevaluable case does not pass, an absent outcome never fires.

# CF-3: a cash_flow claim seats only when inherited context
# (the notehead channel) carries at most half its own score.
CF_CONTEXT_SHARE_CEILING = 0.5

# BS-1: a balance_sheet claim seats only at >= 0.4x the filing's
# strongest balance_sheet claim score. The [.4, .5) band is the
# kill-condition watch: kills at .349/.175/.069, 3 trues inside.
BS_FILING_RELATIVE_FLOOR = 0.4
