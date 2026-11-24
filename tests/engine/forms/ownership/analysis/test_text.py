"""Unit tests for ownership analysis text helpers."""

from __future__ import annotations


def test_mask_normalized_pattern() -> None:
    from edgar_sec.engine.forms.ownership.analysis.text import (
        mask_normalized_pattern,
    )

    assert (
        mask_normalized_pattern("Employee Stock Option 02/06/2002 Grant")
        == "Employee Stock Option DATE_PATTERN Grant"
    )
    assert (
        mask_normalized_pattern("Statement for June 2001") == "Statement for MONTH ###"
    )
    assert mask_normalized_pattern("CIK: 0000123456 filed June 2001") == (
        "CIK_### filed MONTH ###"
    )
