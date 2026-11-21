from __future__ import annotations

from edgar_sec.domain.forms.common.missing_values import MissingValuePolicy

CUSIP_UNAVAILABLE_VALUES = frozenset(
    {
        "none",
        "none.",
        "n/a",
        "n/a.",
        "na",
        "na.",
        "not available",
        "not applicable",
        "not provided",
        "unknown",
    }
)
CUSIP_UNAVAILABLE_POLICY = MissingValuePolicy(accepted_markers=CUSIP_UNAVAILABLE_VALUES)


__all__ = [
    "CUSIP_UNAVAILABLE_POLICY",
    "CUSIP_UNAVAILABLE_VALUES",
]
