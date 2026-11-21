"""The Exhibit 13 type family, spelled once in the domain vocabulary."""

from __future__ import annotations

import pytest

from edgar_sec.domain.forms.exhibits.vocabulary import is_ex13_type


@pytest.mark.parametrize(
    "value",
    [
        "EX-13",
        "EX-13.0",
        "EX-13.1",
        "EX-13.5",
        "EX-13.7",
        "EX-13.01",
        "EX-13.02",
        "EX-13.PDF",
        "EX-13.1.PDF",
        "EX-13.A",
        "EX-13.(A)",
        "EX-13.(A)(I)",
        "EX-13.(A)(II)",
        "EX-13.01(A)",
        "ex-13.01",
        " EX-13.2 ",
    ],
)
def test_ex13_family_spellings_match(value: str) -> None:
    assert is_ex13_type(value)


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "EX-1",
        "EX-130",
        "EX-13X",
        "EX-13.",
        "EX-13.B",
        "EX-99",
        "EX-99.1",
        "10-K",
        "EX-13.1A",
    ],
)
def test_non_family_types_do_not_match(value: str | None) -> None:
    assert not is_ex13_type(value)
