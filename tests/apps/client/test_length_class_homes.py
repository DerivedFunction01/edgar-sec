"""Pins for the length-class homes (Wave 2B).
The span-shaped adapter binds the fiscal home; the fact-shaped
adapter stands diverged, priced by the instant-fact flip case.
"""

from __future__ import annotations

from types import SimpleNamespace

from edgar_sec.apps.client import financials_ttm, fiscal, ttm_comparison


def test_ttm_binding_is_the_fiscal_home() -> None:
    assert ttm_comparison._length_class is fiscal.duration_length_class


def test_ttm_verdicts_match_the_home() -> None:
    for start, end in (("2024-01-01", "2024-03-31"), ("2023-01-01", "2023-12-31")):
        assert ttm_comparison._length_class(start, end) == (
            fiscal.duration_length_class(start, end)
        )


def test_fact_adapter_divergence_pin() -> None:
    # An instant fact with no span: the fact adapter answers None,
    # the fiscal fact home answers INSTANT. The copies stand apart.
    fact = SimpleNamespace(
        period_type="instant",
        instant_date="2024-03-31",
        start_date=None,
        end_date=None,
    )
    assert financials_ttm._span_length_class(fact) is None
    assert fiscal.fact_length_class(fact) == "INSTANT"
