"""Coverage machinery: seed candidates from a retired inventory."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.normalize import normalize_text
from tools.table_extraction_corpus.coverage import (
    build_seed_candidates,
    module_literals,
    phrase_forms,
)


def _inventory() -> dict:
    return {
        "specs": {
            "pension": {
                "name": "pension",
                "source": "tables/families.py FAMILY_SPECS",
                "exclusions": ["activities"],
                "tiers": [
                    {
                        "name": "pension_primary",
                        "support": False,
                        "terms": ["funded status", "benefit obligation"],
                    },
                    {
                        "name": "pension_support",
                        "support": True,
                        "terms": ["discount rate"],
                    },
                ],
            },
            "labor_contracts": {
                "name": "labor_contracts",
                "source": "tables/families.py FAMILY_SPECS",
                "exclusions": [],
                "tiers": [
                    {
                        "name": "labor_primary",
                        "support": False,
                        "terms": ["collective bargaining agreement"],
                    },
                    {
                        "name": "labor_support",
                        "support": True,
                        "terms": ["expanded support phrase number one"],
                    },
                ],
            },
        },
        "literals": {
            "derivatives_hedging": ["notional amount", "interest rate swap"],
            "labor_contracts": ["union employees"],
            "legal_proceedings": ["legal proceedings"],
        },
    }


def _full_inventory() -> dict:
    inventory = _inventory()
    for family in (
        "aoci",
        "cover_layout",
        "debt_maturity",
        "derivatives_hedging",
        "equity_statement",
        "intangibles",
        "ppe",
        "shares_purchased",
        "stock_comp_rollforward",
    ):
        inventory["specs"][family] = {
            "name": family,
            "source": "tables/families.py FAMILY_SPECS",
            "exclusions": [],
            "tiers": [{"name": "primary", "support": False, "terms": ["some phrase"]}],
        }
    return inventory


def test_norm_term_folds_quotes_and_case() -> None:
    assert normalize_text("  Stockholders’   Equity ") == "stockholders' equity"


def test_phrase_forms_include_phrase_bigrams_and_unigrams() -> None:
    forms = phrase_forms("Projected Benefit Obligation")
    assert "projected benefit obligation" in forms
    assert "projected benefit" in forms
    assert "benefit obligation" in forms
    assert "obligation" in forms


def test_module_literals_skip_docstrings() -> None:
    source = '"""Module docstring phrase."""\n\nTERMS = ("funded status", "x")\n'
    assert module_literals(source) == ["funded status"]


def test_seed_candidates_carry_tier_origins() -> None:
    seeds = build_seed_candidates(_full_inventory())
    pension = seeds["families"]["pension"]["forms"]
    assert pension["funded status"]["tiers"] == ["pension_primary"]
    assert pension["discount rate"]["tiers"] == ["pension_support"]
    assert seeds["families"]["pension"]["exclusions"] == ["activities"]


def test_seed_candidates_use_literals_for_combinatorial_specs() -> None:
    seeds = build_seed_candidates(_full_inventory())
    derivatives = seeds["families"]["derivatives_hedging"]["forms"]
    assert derivatives["notional amount"]["tiers"] == ["source-literals"]
    assert "some phrase" not in derivatives


def test_mining_uses_primary_tiers_and_literals_only() -> None:
    seeds = build_seed_candidates(_full_inventory())
    labor = seeds["mining"]["labor_contracts"]["phrases"]
    assert "collective bargaining agreement" in labor
    assert "union employees" in labor
    assert "expanded support phrase number one" not in labor
