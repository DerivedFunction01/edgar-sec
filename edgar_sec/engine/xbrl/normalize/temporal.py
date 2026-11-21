"""Interval-valued temporal facet extracted from concept-name phrasing.

Port of the Phase R prototype (spec section 6): windows, year buckets,
and through-ranges become one half-open month interval on the
expression, and horizon derivation is a stated function of it.
"""

from __future__ import annotations

from dataclasses import dataclass

WINDOW = "WINDOW"
BUCKET = "BUCKET"
RANGE = "RANGE"

_UNIT_MONTHS = {
    "year": 12,
    "years": 12,
    "month": 1,
    "months": 1,
    "quarter": 3,
    "quarters": 3,
}
_WINDOW_LEADS = ("within", "in", "due", "less", "next")
_BUCKET_BLOCKERS = ("within", "next", "less")


@dataclass(frozen=True, slots=True)
class TemporalInterval:
    """A half-open (lo, hi] span in months; hi None means unbounded."""

    lo_months: int
    hi_months: int | None
    shape: str


def _anchored_cardinals(
    tokens: tuple[str, ...], number_values: dict[int, int]
) -> list[tuple[int, int, int]]:
    """Unit-anchored cardinal values as (index, months, unit months)."""
    out: list[tuple[int, int, int]] = []
    for idx, value in sorted(number_values.items()):
        for near in (idx + 1, idx - 1):
            if 0 <= near < len(tokens):
                unit = _UNIT_MONTHS.get(tokens[near].lower())
                if unit:
                    out.append((idx, value * unit, unit))
                    break
    return out


def extract_temporal(
    tokens: tuple[str, ...],
    number_values: dict[int, int],
    ordinal_values: dict[int, int],
) -> TemporalInterval | None:
    """Extract the name's temporal interval from its phrasing patterns."""
    lower = tuple(t.lower() for t in tokens)
    cardinals = _anchored_cardinals(tokens, number_values)
    if len(cardinals) >= 2:
        (i1, m1, _), (i2, m2, _) = cardinals[0], cardinals[1]
        if any(word in ("through", "to") for word in lower[i1 + 1 : i2]):
            return TemporalInterval(min(m1, m2), max(m1, m2), RANGE)
    for idx, value in sorted(ordinal_values.items()):
        if any(
            0 <= j < len(tokens) and lower[j] in ("year", "years")
            for j in (idx - 1, idx + 1)
        ):
            return TemporalInterval((value - 1) * 12, value * 12, BUCKET)
    if not cardinals:
        return None
    idx, months, unit = cardinals[0]
    lead = lower[max(0, idx - 4) : idx]
    due_after = any(lower[j : j + 2] == ("due", "after") for j in range(len(lower) - 1))
    if "after" in lead or due_after:
        return TemporalInterval(months, None, WINDOW)
    if any(word in lead for word in _WINDOW_LEADS):
        if months >= 24 and not any(word in lead for word in _BUCKET_BLOCKERS):
            return TemporalInterval(months - unit, months, BUCKET)
        return TemporalInterval(0, months, WINDOW)
    return None


def derive_horizon(interval: TemporalInterval | None) -> str | None:
    """Derive a horizon bucket from an interval, one-sidedly (spec section 6).

    Inside (0, 12] derives CURRENT; starting at month 12 or later
    derives NONCURRENT; straddling derives nothing.
    """
    if interval is None:
        return None
    if interval.hi_months is not None and interval.hi_months <= 12:
        return "M_CURRENT"
    if interval.lo_months >= 12:
        return "M_NONCURRENT"
    return None
