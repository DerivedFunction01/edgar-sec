"""Tests for shared planning helpers."""

from __future__ import annotations

import pytest

from edgar_sec.pipelines.filing_catalog.planning.shared import validate_forms


def test_validate_forms_success() -> None:
    assert validate_forms(("10-K", "10-Q", "8-K/A")) == ("10-K", "10-Q", "8-K/A")
    assert validate_forms(("10-K", "10-K")) == ("10-K",)


def test_validate_forms_rejects_empty_or_invalid() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        validate_forms(("",))
    with pytest.raises(ValueError, match="unsafe"):
        validate_forms(("10-K; DROP TABLE",))
