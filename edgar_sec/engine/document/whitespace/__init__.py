"""Final whitespace normalization for normalized document text.

Separated from the HTML passes because it runs on the finished text frame —
after cover healing and checkmark rewriting (and before ASCII reflow) — not on
markup. See `normalizer.py` for the three problems it resolves.
"""
