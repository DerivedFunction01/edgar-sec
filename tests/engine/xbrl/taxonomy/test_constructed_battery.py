"""Standing constructed battery over the production decomposer.

Append-only: an act's rows land in the same change that builds its claims.
"""

import pytest

from edgar_sec.engine.xbrl.normalize.decomposer import decompose_concept_expression
from edgar_sec.engine.xbrl.normalize.lexicon import TokenLexicon
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.support import load_fixture

_ROWS = load_fixture("xbrl/act_battery.json")["rows"]
_ROW_KEYS = {"act", "name", "head", "modifiers", "direction", "note"}
_INITIAL_ACTS = {
    "payment",
    "proceeds",
    "borrowing",
    "maturity",
    "dividend",
    "impairment",
    "purchase",
}


@pytest.fixture(scope="module")
def lexicon() -> TokenLexicon:
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    return tax.token_lexicon


@pytest.mark.parametrize("row", _ROWS, ids=[row["name"] for row in _ROWS])
def test_constructed_battery_row(lexicon: TokenLexicon, row: dict) -> None:
    """The constructed name decomposes to its pinned atom and direction."""
    expr = decompose_concept_expression(row["name"], lexicon)
    assert expr.atom.head == row["head"]
    assert set(expr.atom.modifiers) == set(row["modifiers"])
    assert expr.direction == row["direction"]


def test_constructed_battery_initial_coverage() -> None:
    """The initial table covers the accounted acts and purchase."""
    assert _INITIAL_ACTS <= {row["act"] for row in _ROWS}
    assert all(set(row) == _ROW_KEYS for row in _ROWS)
    names = [row["name"] for row in _ROWS]
    assert len(names) == len(set(names))
