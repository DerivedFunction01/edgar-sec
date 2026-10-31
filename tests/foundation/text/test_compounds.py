"""Unit tests for compound expansion and variant generation."""

from edgar_sec.foundation.text.compounds import (
    expand_alternations,
    expand_compounds,
    expand_variants,
)


def test_expand_alternations_dedup_and_sort() -> None:
    res = expand_alternations(["form 10-k", "item 1a", "form 10-k", "item 7"])
    assert res == ("form 10-k", "item 1a", "item 7")


def test_expand_variants_plurals_and_spelling() -> None:
    variants = expand_variants("color", plurals=True, us_uk_spelling=True)
    assert "color" in variants
    assert "colour" in variants
    assert "colors" in variants
    assert "colours" in variants


def test_expand_compounds_cartesian() -> None:
    compounds = expand_compounds(
        ["collective", "labor"],
        ["bargaining", "agreement"],
    )
    assert "collective bargaining" in compounds
    assert "collective agreement" in compounds
    assert "labor bargaining" in compounds
    assert "labor agreement" in compounds


def test_expand_compounds_optional_slot() -> None:
    compounds = expand_compounds(
        ["union"],
        [None, "pension"],
        ["plan", "plans"],
    )
    assert "union plan" in compounds
    assert "union plans" in compounds
    assert "union pension plan" in compounds
    assert "union pension plans" in compounds
