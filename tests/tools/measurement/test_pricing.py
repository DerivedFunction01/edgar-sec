"""Generic pricing evaluator: verdicts, cells, board, command."""

import json

import pytest

from edgar_sec.tools.measurement.pricing import (
    FAIL,
    PASS,
    UNEVALUABLE,
    evaluate,
    main,
    packet_board,
    price_cell,
    price_packet,
)


def spec(key, member, claimed=False, residual=False, **features):
    return {
        "key": key,
        "member": member,
        "claimed": claimed,
        "residual": residual,
        "features": features,
    }


def test_atoms_and_missing_features():
    s = spec("a", True, n=3, flag=True)
    assert evaluate({"feature": "flag", "op": "truthy"}, s, {}) == PASS
    assert evaluate({"feature": "flag", "op": "falsy"}, s, {}) == FAIL
    assert evaluate({"feature": "n", "op": "ge", "value": 3}, s, {}) == PASS
    assert evaluate({"feature": "n", "op": "lt", "value": 3}, s, {}) == FAIL
    assert evaluate({"feature": "n", "op": "eq", "value": 3}, s, {}) == PASS
    assert evaluate({"feature": "n", "op": "ne", "value": 3}, s, {}) == FAIL
    assert evaluate({"feature": "gone", "op": "truthy"}, s, {}) == UNEVALUABLE
    assert evaluate({"feature": "n", "op": "ge", "value": "x"}, s, {}) == (UNEVALUABLE)


def test_verdict_feature_and_reserved_fields():
    s = spec("a", True, claimed=True, leg="fail")
    assert evaluate({"feature": "leg", "op": "verdict"}, s, {}) == FAIL
    s2 = spec("b", False, leg="sparse")
    assert evaluate({"feature": "leg", "op": "verdict"}, s2, {}) == UNEVALUABLE
    assert evaluate({"feature": "claimed", "op": "truthy"}, s, {}) == PASS
    assert evaluate({"feature": "member", "op": "truthy"}, s2, {}) == FAIL


def test_combinators_are_three_valued():
    s = spec("a", True, x="pass", y="unevaluable", z="fail")
    vx = {"feature": "x", "op": "verdict"}
    vy = {"feature": "y", "op": "verdict"}
    vz = {"feature": "z", "op": "verdict"}
    assert evaluate({"all": [vx, vy]}, s, {}) == UNEVALUABLE
    assert evaluate({"all": [vx, vz]}, s, {}) == FAIL
    assert evaluate({"any": [vx, vz]}, s, {}) == PASS
    assert evaluate({"any": [vy, vz]}, s, {}) == UNEVALUABLE
    assert evaluate({"refusal": [vx, vz]}, s, {}) == FAIL
    assert evaluate({"refusal": [vx, vy]}, s, {}) == PASS
    assert evaluate({"refusal": [vy]}, s, {}) == UNEVALUABLE
    assert evaluate({"not": vx}, s, {}) == FAIL
    assert evaluate({"not": vy}, s, {}) == UNEVALUABLE


def test_rule_references_and_cycle():
    rules = {
        "base": {"feature": "n", "op": "ge", "value": 2},
        "combo": {"all": [{"rule": "base"}, {"feature": "flag", "op": "truthy"}]},
    }
    s = spec("a", True, n=3, flag=True)
    assert evaluate({"rule": "combo"}, s, rules) == PASS
    loop = {"a": {"rule": "b"}, "b": {"rule": "a"}}
    with pytest.raises(ValueError):
        evaluate({"rule": "a"}, s, loop)


def _packet():
    return [
        spec("m1", True, claimed=True, period=4, purchase=True),
        spec("m2", True, claimed=True, period=1, purchase=True),
        spec("m3", True, claimed=False, period=4, purchase=True),
        spec("f1", False, claimed=True, period=4, purchase=True),
        spec("f2", False, claimed=True, period=0, purchase=False, residual=True),
        spec("u1", None, claimed=True, period=None, purchase=True),
    ]


_LADDER = {
    "all": [
        {"feature": "purchase", "op": "truthy"},
        {"feature": "period", "op": "ge", "value": 3},
    ]
}


def test_necessary_cell_counts_kills_touches_and_verdicts():
    cell = price_cell(
        _packet(), _LADDER, {}, scope={"feature": "claimed", "op": "truthy"}
    )
    assert cell["kills"] == 1 and cell["kills_of"] == 2
    assert cell["touches"] == 1 and cell["touches_of"] == 2
    assert cell["verdicts"] == {"pass": 2, "fail": 2, "unevaluable": 1}
    assert cell["killed_keys"] == ["f2"]
    assert cell["touched_keys"] == ["m2"]
    assert cell["population"] == 5


def test_kill_cell_unions_patterns_and_names_residuals():
    cover = {
        "any": [
            {"feature": "period", "op": "le", "value": 0},
            {"feature": "purchase", "op": "falsy"},
        ]
    }
    cell = price_cell(_packet(), cover, {}, form="kill")
    assert cell["kills"] == 1 and cell["touches"] == 0
    assert cell["residual_kills"] == 1
    assert cell["residual_killed_keys"] == ["f2"]


def test_selection_cell_prices_precision_and_recall():
    cell = price_cell(_packet(), _LADDER, {}, form="selection")
    assert cell["selected"] == 3
    assert cell["selected_members"] == 2
    assert cell["selected_falses"] == 1
    assert cell["precision"] == round(2 / 3, 4)
    assert cell["recall"] == round(2 / 3, 4)
    assert cell["unevaluable"] == 1


def test_board_counts_claims_over_labeled_only():
    board = packet_board(_packet())
    assert board["specimens"] == 6
    assert board["members"] == 3 and board["falses"] == 2
    assert board["unlabeled"] == 1
    assert board["tp"] == 2 and board["fp"] == 2 and board["fn"] == 1


def test_price_packet_and_main_round_trip(tmp_path):
    packet = {
        "specimens": _packet(),
        "rules": {"ladder": _LADDER},
        "cells": [
            {
                "name": "ladder_claimed",
                "rule": "ladder",
                "scope": {"feature": "claimed", "op": "truthy"},
            }
        ],
    }
    result = price_packet(packet)
    assert result["cells"]["ladder_claimed"]["kills"] == 1
    src = tmp_path / "packet.json"
    out = tmp_path / "cells.json"
    src.write_text(json.dumps(packet))
    assert main([str(src), str(out)]) == 0
    assert json.loads(out.read_text())["cells"]["ladder_claimed"]["touches"] == 1
