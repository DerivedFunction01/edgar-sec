"""Census assembly: precedence joins, text stores, residual lists."""

from __future__ import annotations

import json

from edgar_sec.tools.table_extraction_corpus.census_assembly import (
    assemble,
    main,
    residual_lists,
)

FALSE_SID = "1000000001-24-000001:9"
TRUE_SID = "1000000001-24-000001:1"
IMPOSTER_SID = "1000000001-24-000001:2"
PENSION_SID = "2000000002-24-000001:1"
GOLD_SID = "4000000004-24-000001:1"
SUPPLEMENT_SID = "5000000005-24-000001:1"


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _jsonl(rows):
    return "".join(json.dumps(r) + "\n" for r in rows)


def _inputs(root):
    _write(
        root / "step1" / "register-step1.json",
        json.dumps(
            {
                "false_claims": [
                    {
                        "specimen_id": FALSE_SID,
                        "family": "goodwill",
                        "final_class": "composition",
                        "true_family": None,
                        "mechanism": "caption-echo",
                        "stratum": "B",
                    }
                ]
            }
        ),
    )
    _write(
        root / "bases" / "s4.jsonl",
        _jsonl(
            [
                {"specimen_id": TRUE_SID, "label": "TRUE"},
                {"specimen_id": IMPOSTER_SID, "label": "IMPOSTER"},
                {
                    "accession": "1000000001-24-000001",
                    "table_index": 3,
                    "label": "LINE-ITEM",
                },
                {"label": "NEAR-MISS"},
            ]
        ),
    )
    _write(
        root / "step9" / "core-populations.json",
        json.dumps(
            {
                "pops": {"true_pen_grouped": [PENSION_SID]},
                "packets": {
                    PENSION_SID: {
                        "caption_stack": ["Pension note"],
                        "prose_before": "before",
                        "prose_after": "after",
                        "table_text": "A | B",
                    }
                },
            }
        ),
    )
    _write(root / "step9" / "pops.json", json.dumps({}))
    _write(root / "step9" / "cache.json", json.dumps({"packets": {}}))
    _write(
        root / "step8" / "fair_value.txt",
        f"===== {GOLD_SID}\n"
        "caption_stack: ['Fair value note']\n"
        "prose_before: 'gold before'\n"
        "table_text:\n"
        "Level | Amount\n",
    )
    _write(
        root / "step1pk" / "packets-b.jsonl",
        _jsonl(
            [
                {
                    "specimen_id": FALSE_SID,
                    "caption_stack": ["Goodwill note"],
                    "prose_before": "false before",
                    "prose_after": "",
                    "table_text": "X | Y",
                },
                {
                    "specimen_id": TRUE_SID,
                    "caption_stack": [],
                    "prose_before": "",
                    "prose_after": "",
                    "table_text": "Z | W",
                },
            ]
        ),
    )
    _write(
        root / "step1pk" / "verdicts-final" / "grouped-b.jsonl",
        _jsonl(
            [
                {
                    "specimen_id": SUPPLEMENT_SID,
                    "family": "cash_flow",
                    "verdict": "member",
                }
            ]
        ),
    )
    return root


def _rows(out_dir):
    text = (out_dir / "census-population.jsonl").read_text()
    return [json.loads(ln) for ln in text.splitlines()]


def test_assemble_joins_by_precedence_and_attaches_text(tmp_path):
    out = tmp_path / "out"
    summary = assemble(_inputs(tmp_path / "inputs"), out)
    assert summary["units"] == 4
    assert summary["falses"] == 2
    assert summary["pop_rows"] == 6
    assert summary["errors"] > 0
    rows = {(r["family"], r["sid"]): r for r in _rows(out)}
    false_row = rows[("goodwill", FALSE_SID)]
    assert false_row["side"] == "false"
    assert false_row["source"] == "step1-register"
    assert false_row["text_source"] == "step1-packets"
    assert false_row["table_text"] == "X | Y"
    imposter = rows[("goodwill", IMPOSTER_SID)]
    assert imposter["final_class"] == "base-label:IMPOSTER"
    assert imposter["label"] == "IMPOSTER"
    assert rows[("goodwill", TRUE_SID)]["source"] == ["base:s4.jsonl"]
    pension = rows[("pension", PENSION_SID)]
    assert pension["text_source"] == "step9-lane-b-packets"
    gold = rows[("fair_value", GOLD_SID)]
    assert gold["source"] == ["step8-golds"]
    assert gold["prose_before"] == "gold before"
    supplement = rows[("cash_flow", SUPPLEMENT_SID)]
    assert supplement["source"] == ["step1-verdicts"]
    assert supplement["text_source"] is None


def test_assemble_account_counts_labels_and_unjoinable(tmp_path):
    out = tmp_path / "out"
    assemble(_inputs(tmp_path / "inputs"), out)
    account = json.loads((out / "census-assembly.json").read_text())
    assert account["total_falses"] == 2
    assert account["total_true_rows"] == 4
    assert account["label_distributions"]["s4.jsonl"] == {
        "TRUE": 1,
        "IMPOSTER": 1,
        "LINE-ITEM": 1,
        "NEAR-MISS": 1,
    }
    assert account["unjoinable_base_rows"] == {"s4.jsonl": {"NEAR-MISS": 1}}
    assert account["gold_families"] == {"fair_value": 1}
    goodwill = account["per_family"]["goodwill"]
    assert goodwill["falses"] == 2
    assert goodwill["trues"] == 1
    assert goodwill["trues_by_source"] == {"base:s4.jsonl": 1}


def test_assemble_is_deterministic(tmp_path):
    inputs = _inputs(tmp_path / "inputs")
    first, second = tmp_path / "a", tmp_path / "b"
    assemble(inputs, first)
    assemble(inputs, second)
    for name in ("census-population.jsonl", "census-assembly.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_residual_lists_render():
    pricing = {
        "alpha": {
            "residual": [
                {
                    "sid": "1000000001-24-000001:9",
                    "final_class": "composition",
                    "mechanism": None,
                    "firm": "1000000001",
                    "core_terms_carried": ["term a", "term b"],
                    "killed_by_lexical_single": True,
                }
            ]
        },
        "beta": {"residual": []},
    }
    assert residual_lists(pricing) == (
        "## alpha residual 1\n"
        "1000000001-24-000001:9 | composition | mech=None"
        " | firm=1000000001 | core_carried=2 | lexical=True"
    )


def test_main_round_trips_with_pricing(tmp_path):
    inputs = _inputs(tmp_path / "inputs")
    pricing = tmp_path / "pricing.json"
    pricing.write_text(json.dumps({"alpha": {"residual": []}}))
    out = tmp_path / "out"
    assert main([str(inputs), str(out), "--pricing", str(pricing)]) == 0
    assert (out / "census-population.jsonl").exists()
    assert (out / "residual-lists.txt").read_text() == ""
