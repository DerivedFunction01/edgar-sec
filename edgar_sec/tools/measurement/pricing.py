"""Generic per-family feature pricing evaluator.

Packet + rule set + adjudicated bases in; priced cells out: claims,
kills, touches, and combination cells in the Ruling 17 form.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from edgar_sec.infra.storage.atomic import atomic_write_json

PASS = "pass"
FAIL = "fail"
UNEVALUABLE = "unevaluable"

_COMPARE_OPS = ("ge", "le", "gt", "lt", "eq", "ne", "in")
_RESERVED = ("member", "claimed", "residual")


def _feature(specimen: dict, name: str):
    feats = specimen.get("features") or {}
    if name in feats:
        return feats[name]
    if name in _RESERVED:
        value = specimen.get(name)
        return value if name == "member" else bool(value)
    return None


def evaluate(spec: dict, specimen: dict, rules: dict, seen: tuple = ()) -> str:
    """Three-valued verdict of one rule spec over one specimen.

    A spec is an atom (feature test), a combinator (all / any /
    refusal / not), or a reference to a named rule in the set.
    """
    if "rule" in spec:
        name = spec["rule"]
        if name in seen:
            raise ValueError(f"rule reference cycle at {name!r}")
        return evaluate(rules[name], specimen, rules, seen + (name,))
    if "all" in spec:
        verdicts = [evaluate(s, specimen, rules, seen) for s in spec["all"]]
        if FAIL in verdicts:
            return FAIL
        return UNEVALUABLE if UNEVALUABLE in verdicts else PASS
    if "any" in spec:
        verdicts = [evaluate(s, specimen, rules, seen) for s in spec["any"]]
        if PASS in verdicts:
            return PASS
        return UNEVALUABLE if UNEVALUABLE in verdicts else FAIL
    if "refusal" in spec:
        # Presented-leg form: a failing leg refuses, a passing leg
        # admits, and no leg presented reads unevaluable.
        verdicts = [evaluate(s, specimen, rules, seen) for s in spec["refusal"]]
        if FAIL in verdicts:
            return FAIL
        return PASS if PASS in verdicts else UNEVALUABLE
    if "not" in spec:
        verdict = evaluate(spec["not"], specimen, rules, seen)
        if verdict == UNEVALUABLE:
            return UNEVALUABLE
        return FAIL if verdict == PASS else PASS
    return _atom(spec, specimen)


def _atom(spec: dict, specimen: dict) -> str:
    value = _feature(specimen, spec["feature"])
    op = spec["op"]
    if op == "verdict":
        # The feature itself carries a three-valued verdict, as a
        # family reader's per-leg read does.
        return value if value in (PASS, FAIL, UNEVALUABLE) else UNEVALUABLE
    if value is None:
        return UNEVALUABLE
    if op == "truthy":
        return PASS if value else FAIL
    if op == "falsy":
        return PASS if not value else FAIL
    if op in _COMPARE_OPS:
        return _compare(op, value, spec.get("value"))
    raise ValueError(f"unknown rule op {op!r}")


def _compare(op: str, value, target) -> str:
    try:
        if op == "ge":
            ok = value >= target
        elif op == "le":
            ok = value <= target
        elif op == "gt":
            ok = value > target
        elif op == "lt":
            ok = value < target
        elif op == "eq":
            ok = value == target
        elif op == "in":
            ok = value in target
        else:
            ok = value != target
    except TypeError:
        return UNEVALUABLE
    return PASS if ok else FAIL


def _scoped(specimens: list, rules: dict, scope: dict | None) -> list:
    if scope is None:
        return list(specimens)
    return [s for s in specimens if evaluate(scope, s, rules) == PASS]


def _tally(specimens: list, spec: dict, rules: dict) -> list:
    return [(s, evaluate(spec, s, rules)) for s in specimens]


def _necessary(pop: list, spec: dict, rules: dict) -> dict:
    killed, touched, verdicts = [], [], {PASS: 0, FAIL: 0, UNEVALUABLE: 0}
    unevaluable = {"falses": 0, "members": 0}
    for specimen, verdict in _tally(pop, spec, rules):
        verdicts[verdict] += 1
        if verdict == UNEVALUABLE:
            if specimen.get("member") is True:
                unevaluable["members"] += 1
            elif specimen.get("member") is False:
                unevaluable["falses"] += 1
        elif verdict == FAIL:
            if specimen.get("member") is True:
                touched.append(specimen["key"])
            elif specimen.get("member") is False:
                killed.append(specimen["key"])
    return {
        "form": "necessary",
        "kills": len(killed),
        "kills_of": sum(1 for s in pop if s.get("member") is False),
        "touches": len(touched),
        "touches_of": sum(1 for s in pop if s.get("member") is True),
        "unevaluable_falses": unevaluable["falses"],
        "unevaluable_members": unevaluable["members"],
        "verdicts": verdicts,
        "killed_keys": sorted(killed),
        "touched_keys": sorted(touched),
    }


def _kill(pop: list, spec: dict, rules: dict) -> dict:
    killed, touched, residual = [], [], []
    for specimen, verdict in _tally(pop, spec, rules):
        if verdict != PASS:
            continue
        if specimen.get("member") is True:
            touched.append(specimen["key"])
        elif specimen.get("member") is False:
            killed.append(specimen["key"])
            if specimen.get("residual"):
                residual.append(specimen["key"])
    return {
        "form": "kill",
        "kills": len(killed),
        "kills_of": sum(1 for s in pop if s.get("member") is False),
        "touches": len(touched),
        "touches_of": sum(1 for s in pop if s.get("member") is True),
        "residual_kills": len(residual),
        "residual_killed_keys": sorted(residual),
        "killed_keys": sorted(killed),
        "touched_keys": sorted(touched),
    }


def _selection(pop: list, spec: dict, rules: dict) -> dict:
    selected, members, falses, unevaluable = [], 0, 0, 0
    for specimen, verdict in _tally(pop, spec, rules):
        if verdict == UNEVALUABLE:
            unevaluable += 1
        elif verdict == PASS:
            selected.append(specimen["key"])
            if specimen.get("member") is True:
                members += 1
            elif specimen.get("member") is False:
                falses += 1
    total_members = sum(1 for s in pop if s.get("member") is True)
    decided = members + falses
    return {
        "form": "selection",
        "selected": len(selected),
        "selected_members": members,
        "selected_falses": falses,
        "precision": round(members / decided, 4) if decided else None,
        "recall": round(members / total_members, 4) if total_members else None,
        "unevaluable": unevaluable,
        "selected_keys": sorted(selected),
    }


_FORMS = {"necessary": _necessary, "kill": _kill, "selection": _selection}


def price_cell(
    specimens: list,
    spec: dict,
    rules: dict,
    scope: dict | None = None,
    form: str = "necessary",
) -> dict:
    """Price one rule spec over a packet, optionally scoped."""
    pop = _scoped(specimens, rules, scope)
    cell = _FORMS[form](pop, spec, rules)
    cell["population"] = len(pop)
    cell["members"] = sum(1 for s in pop if s.get("member") is True)
    cell["falses"] = sum(1 for s in pop if s.get("member") is False)
    return cell


def packet_board(specimens: list) -> dict:
    """Claim accounting over a packet's adjudicated specimens."""
    members = [s for s in specimens if s.get("member") is True]
    falses = [s for s in specimens if s.get("member") is False]
    claimed_m = [s for s in members if s.get("claimed")]
    claimed_f = [s for s in falses if s.get("claimed")]
    return {
        "specimens": len(specimens),
        "members": len(members),
        "falses": len(falses),
        "unlabeled": len(specimens) - len(members) - len(falses),
        "claimed_members": len(claimed_m),
        "claimed_falses": len(claimed_f),
        "tp": len(claimed_m),
        "fp": len(claimed_f),
        "fn": len(members) - len(claimed_m),
    }


def price_packet(packet: dict) -> dict:
    """Price every cell a packet names, over its own specimens."""
    specimens = packet["specimens"]
    rules = packet.get("rules") or {}
    cells = {}
    for request in packet.get("cells") or []:
        spec = rules[request["rule"]] if "rule" in request else request["spec"]
        cells[request["name"]] = price_cell(
            specimens,
            spec,
            rules,
            scope=request.get("scope"),
            form=request.get("form", "necessary"),
        )
    return {"board": packet_board(specimens), "cells": cells}


def main(argv: list[str] | None = None) -> int:
    """Price a packet file into a priced-cells file."""
    parser = argparse.ArgumentParser(prog="pricing")
    parser.add_argument("packet", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args(argv)
    packet = json.loads(args.packet.read_text())
    result = price_packet(packet)
    atomic_write_json(args.out, result, canonical=False, indent=1)
    summary = {}
    for name, cell in result["cells"].items():
        keys = (
            ("kills", "touches")
            if "kills" in cell
            else ("selected", "precision", "recall")
        )
        summary[name] = {k: cell[k] for k in keys}
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
