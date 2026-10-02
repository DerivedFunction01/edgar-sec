"""The declarative rule cascade and the calibrated feature registry.

`thresholds.py` holds the 44 calibrated feature predicates that decide whether a
measured scalar counts as evidence of prose or of a table. `cascades.py` holds
the ordered rules built on top of them, plus the block-to-decision mapping.

The thresholds are calibrated, not chosen. Their count and their split points
are pinned by `tests/engine/reflow/rules/test_thresholds.py`, so a later edit
that tidies one of them fails loudly rather than silently moving a boundary.
"""
