"""Contract and unit tests for domain-neutral Cartesian compound and alternation string builder."""

from __future__ import annotations

from enum import Enum

from defs.text.compounds import (
    expand_alternations,
    expand_compounds,
    expand_variants,
)


class SampleTier(Enum):
    ALPHA = "alpha tier"
    BETA = "beta tier"


def test_expand_alternations_basic():
    items = ["  Apple  ", "banana", ["apple", "cherry", SampleTier.ALPHA]]
    res = expand_alternations(items)
    assert "apple" in res
    assert "banana" in res
    assert "cherry" in res
    assert "alpha tier" in res
    # Ensure deduplicated
    assert len([x for x in res if x == "apple"]) == 1
    # Longest first: "alpha tier" (2 words) comes before "banana"
    assert res.index("alpha tier") < res.index("banana")


def test_expand_variants():
    res = expand_variants(["labor", "agreement", "craftsman"])
    assert "labor" in res
    assert "labour" in res
    assert "labors" in res
    assert "labours" in res
    assert "agreement" in res
    assert "agreements" in res
    assert "craftsman" in res
    assert "craftsmen" in res


def test_expand_compounds_cartesian():
    prefixes = ["collective", "labor"]
    stems = ["bargaining", "agreement"]
    res = expand_compounds(prefixes, stems)
    assert res == (
        "collective bargaining",
        "collective agreement",
        "labor bargaining",
        "labor agreement",
    )


def test_expand_compounds_optional_slot():
    prefixes = ["union"]
    optional_mid = [None, "pension"]
    suffixes = ["plan", "plans"]

    res = expand_compounds(prefixes, optional_mid, suffixes)
    assert "union pension plans" in res
    assert "union pension plan" in res
    assert "union plans" in res
    assert "union plan" in res


def test_expand_compounds_empty_slots():
    assert expand_compounds() == ()
    assert expand_compounds([]) == ()
    assert expand_compounds(None) == ()
