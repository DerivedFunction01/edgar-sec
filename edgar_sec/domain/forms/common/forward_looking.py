"""Canonical forward-looking, safe harbor, and cautionary disclosure vocabulary.

Statutory safe harbor language (PSLRA) shared across periodic (10-K, 10-Q, 20-F) and
event (8-K, 6-K) reports.
"""

from __future__ import annotations

FORWARD_LOOKING_PHRASES: tuple[str, ...] = (
    "forward-looking statements",
    "forward looking statements",
    "forward-looking information",
    "forward looking information",
    "special note regarding forward-looking statements",
    "special note regarding forward-looking",
    "special note regarding forward looking",
    "cautionary statement regarding forward-looking statements",
    "cautionary statements",
    "cautionary note",
    "safe harbor statement",
    "safe harbor statements",
    "safe harbor",
)

# (Comprises the full 16-token universal safe harbor disclosure formula)
FORWARD_LOOKING_TERMS: tuple[str, ...] = (
    "forward",
    "looking",
    "actual",
    "results",
    "materially",
    "risks",
    "differ",
    "uncertainties",
    "believe",
    "expect",
    "anticipate",
    "estimate",
    "intend",
    "following",
    "certain",
    "may",
)

# Predictive / future-looking verbs in base and third-person forms
FORWARD_LOOKING_VERBS: tuple[str, ...] = (
    "expects",
    "believes",
    "anticipates",
    "estimates",
    "intends",
    "expect",
    "believe",
    "anticipate",
    "estimate",
    "intend",
    "forecast",
    "forecasts",
    "project",
    "projects",
)

__all__ = [
    "FORWARD_LOOKING_PHRASES",
    "FORWARD_LOOKING_TERMS",
    "FORWARD_LOOKING_VERBS",
]
