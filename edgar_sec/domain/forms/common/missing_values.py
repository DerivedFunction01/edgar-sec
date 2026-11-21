from __future__ import annotations

from dataclasses import dataclass

_CLASSIFIED_MARKERS = frozenset(
    {
        "",
        "-",
        "--",
        "none",
        "none.",
        "n/a",
        "n/a.",
        "na",
        "na.",
        "n.a.",
        "n / a",
        "nil",
        "null",
        "not available",
        "not applicable",
        "not provided",
        "not reported",
        "unknown",
        "unknown.",
    }
)


def normalize_missing_value_token(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.split()).casefold()


def classify_missing_value_token(value: str | None) -> str | None:
    normalized = normalize_missing_value_token(value)
    if normalized in _CLASSIFIED_MARKERS:
        return normalized
    return None


@dataclass(frozen=True, slots=True)
class MissingValuePolicy:
    accepted_markers: frozenset[str]

    def is_missing(self, value: str | None) -> bool:
        marker = classify_missing_value_token(value)
        return marker is not None and marker in self.accepted_markers


COMMON_NUMERIC_NULL_POLICY = MissingValuePolicy(
    accepted_markers=frozenset({"", "-", "--", "none", "n/a", "nil", "null"})
)

__all__ = [
    "COMMON_NUMERIC_NULL_POLICY",
    "MissingValuePolicy",
    "classify_missing_value_token",
    "normalize_missing_value_token",
]
