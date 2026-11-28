"""Shadow learner: residual parsing, certification, held-out refusal."""

from __future__ import annotations

import hashlib
import json

from edgar_sec.tools.table_extraction_corpus.shadow_learner import (
    learn_population,
    main,
    parse_residual_lists,
)

TRUE_TABLE = "Cash and equivalents | 10 | 20\nTotal assets | 100 | 200"
FALSE_TABLE = "Notes payable | 5 | 6\nOther current items | 7 | 8"
TRUE_PROSE = "The balance sheets present the position."
FALSE_PROSE = "The following table presents the activity."


def _row(sid, family, side, table_text, prose, *, text_source="primary"):
    return {
        "sid": sid,
        "family": family,
        "side": side,
        "table_text": table_text,
        "caption_stack": ["Note 1 - Summary"],
        "prose_before": prose,
        "prose_after": "See accompanying notes.",
        "text_source": text_source,
        "final_class": None,
        "mechanism": None,
        "true_family": None,
    }


def _half(sid):
    return int(hashlib.sha1(sid.encode()).hexdigest()[:8], 16) % 2


def _balanced_false_sids(per_half):
    picked = {0: [], 1: []}
    i = 0
    while len(picked[0]) < per_half or len(picked[1]) < per_half:
        sid = f"9000000009-24-{i:06d}:9"
        if len(picked[_half(sid)]) < per_half:
            picked[_half(sid)].append(sid)
        i += 1
    return picked[0] + picked[1]


def _population():
    rows = [
        _row(f"1000000001-24-{i:06d}:1", "alpha", "true", TRUE_TABLE, TRUE_PROSE)
        for i in range(20)
    ]
    alpha_falses = _balanced_false_sids(6)
    rows += [
        _row(sid, "alpha", "false", FALSE_TABLE, FALSE_PROSE) for sid in alpha_falses
    ]
    rows += [
        _row(f"3000000003-24-{i:06d}:3", "gamma", "true", TRUE_TABLE, TRUE_PROSE)
        for i in range(4)
    ]
    gamma_falses = [f"4000000004-24-{i:06d}:4" for i in range(4)]
    rows += [
        _row(sid, "gamma", "false", TRUE_TABLE, TRUE_PROSE) for sid in gamma_falses
    ]
    rows += [
        _row(f"5000000005-24-{i:06d}:5", "beta", "true", TRUE_TABLE, TRUE_PROSE)
        for i in range(2)
    ]
    residuals = {"alpha": alpha_falses, "gamma": gamma_falses}
    pricing = {
        "alpha": {"residual": [{"sid": s} for s in alpha_falses]},
        "gamma": {"residual": [{"sid": s} for s in gamma_falses]},
    }
    return rows, residuals, pricing


def test_parse_residual_lists_reads_family_sections():
    lines = ["## alpha x", "sid1|a", "", "sid2", "## beta", "sid3|b"]
    assert parse_residual_lists(lines) == {"alpha": ["sid1", "sid2"], "beta": ["sid3"]}


def test_certified_conjunction_reproduces():
    rows, residuals, pricing = _population()
    register = learn_population(rows, residuals, pricing)
    alpha = register["families"]["alpha"]
    assert alpha["budget"] == 2
    assert alpha["programme_residual"] == 12
    named = [
        r
        for r in alpha["supported"]
        if r["steps"] == [["is", "B:prose:sheets"], ["is", "B:stub:total assets"]]
    ]
    assert len(named) == 1
    rule = named[0]
    assert rule["full_kills"] == 12
    assert rule["full_touches"] == 0
    assert rule["ho_kills"] == 12
    assert rule["ho_touches_scaled"] == 0


def test_no_certification_and_empty_residual_families():
    rows, residuals, pricing = _population()
    register = learn_population(rows, residuals, pricing)
    gamma = register["families"]["gamma"]
    assert gamma["supported"] == []
    assert gamma["note"] == "learner finds nothing beyond the rule prices"
    beta = register["families"]["beta"]
    assert beta["supported"] == []
    assert beta["note"] == "no programme-residual falses to target"
    totals = register["population"]
    assert totals == {
        "rows": 42,
        "falses": 16,
        "trues": 26,
        "programme_residual_total": 16,
        "census_residual_total": 16,
    }


def test_learn_population_is_deterministic():
    rows, residuals, pricing = _population()
    assert learn_population(rows, residuals, pricing) == learn_population(
        rows, residuals, pricing
    )


def test_main_round_trips_census_artifacts(tmp_path):
    rows, residuals, pricing = _population()
    pop = tmp_path / "population.jsonl"
    pop.write_text("".join(json.dumps(r) + "\n" for r in rows))
    resid = tmp_path / "residual-lists.txt"
    lines = []
    for fam, sids in residuals.items():
        lines.append(f"## {fam}")
        lines += [f"{s}|x" for s in sids]
    resid.write_text("\n".join(lines) + "\n")
    price = tmp_path / "pricing.json"
    price.write_text(json.dumps(pricing))
    out = tmp_path / "shadow.json"
    assert main([str(pop), str(resid), str(price), str(out)]) == 0
    assert json.loads(out.read_text()) == learn_population(rows, residuals, pricing)
