"""Claims driver: specimen keying, emit over a staged corpus, diff."""

from __future__ import annotations

import json

from edgar_sec.tools.table_extraction_corpus.claims_driver import (
    claim_sets,
    diff_emit_dirs,
    emit_claims,
    main,
    member_keys,
    occurrence_ordinals,
    parse_fxspec,
    specimen_key,
)

ACCESSION = "1000000001-24-000001"


def _filing_doc():
    return {
        "accession": ACCESSION,
        "geometries": [
            {
                "table_index": 5,
                "header_row_count": 1,
                "rows": [["", "2024"], ["Revenue", "100"], ["Total revenue", "100"]],
            },
            {
                "table_index": 5,
                "header_row_count": 1,
                "rows": [["", "2024"], ["Cost", "40"], ["Total cost", "40"]],
            },
            {
                "table_index": 9,
                "header_row_count": 1,
                "rows": [["Note"], ["Some narrative text here"]],
            },
        ],
    }


def _bases():
    return {"members": {"E": {"intangibles": [{"specimen_id": f"{ACCESSION}:5"}]}}}


def _stage(tmp_path):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "filing.json").write_text(json.dumps(_filing_doc()))
    bases = tmp_path / "bases.json"
    bases.write_text(json.dumps(_bases()))
    return fixtures, bases


def test_specimen_keying_and_ordinals():
    geoms = [{"table_index": 5}, {"table_index": 5}, {"table_index": 9}, {}]
    assert occurrence_ordinals(geoms) == [0, 1, 0, 0]
    assert specimen_key(ACCESSION, 5, 1) == f"{ACCESSION}:5#1"
    assert specimen_key(ACCESSION, None, 0) == f"{ACCESSION}:0#0"


def test_parse_fxspec_and_member_keys():
    assert parse_fxspec("/some/dir:E") == ("/some/dir", "E")
    assert member_keys(_bases()) == {"intangibles": {f"{ACCESSION}:5"}}


def test_claim_sets_key_by_bare_specimen():
    rows = [
        {"specimen": "a:1#0", "claims": ["intangibles"]},
        {"specimen": "a:1#1", "claims": ["intangibles", "other"]},
        {"specimen": "a:2#0", "claims": []},
    ]
    assert claim_sets(rows) == {"intangibles": {"a:1"}, "other": {"a:1"}}


def test_emit_stages_drives_and_logs_gold(tmp_path):
    fixtures, bases = _stage(tmp_path)
    out = tmp_path / "emit"
    summary = emit_claims([(str(fixtures), "E")], bases, out, workers=1)
    assert summary["filings"] == 1
    assert summary["geometries"] == 3
    assert summary["gold_rows"] == 2
    rows = [json.loads(ln) for ln in (out / "rows.jsonl").read_text().splitlines()]
    assert [r["specimen"] for r in rows] == [
        f"{ACCESSION}:5#0",
        f"{ACCESSION}:5#1",
        f"{ACCESSION}:9#0",
    ]
    assert all(r["stratum"] == "E" for r in rows)
    gold = [json.loads(ln) for ln in (out / "gold.jsonl").read_text().splitlines()]
    assert {g["bare"] for g in gold} == {f"{ACCESSION}:5"}
    assert all(g["family"] == "intangibles" for g in gold)


def test_diff_equal_and_divergent(tmp_path):
    fixtures, bases = _stage(tmp_path)
    out = tmp_path / "emit"
    emit_claims([(str(fixtures), "E")], bases, out, workers=1)
    verdict = diff_emit_dirs(out, out, bases)
    assert verdict["equal"]
    assert verdict["members"]["intangibles"]["emit_member_claims"] in (0, 1)
    gold = tmp_path / "gold"
    gold.mkdir()
    extra = {"specimen": "x:1#0", "accession": "x", "stratum": "E",
             "claims": ["intangibles"]}
    rows = (out / "rows.jsonl").read_text() + json.dumps(extra) + "\n"
    (gold / "rows.jsonl").write_text(rows)
    (gold / "summary.json").write_text((out / "summary.json").read_text())
    diverged = diff_emit_dirs(out, gold, bases)
    assert not diverged["equal"]


def test_main_emit_then_diff_round_trip(tmp_path):
    fixtures, bases = _stage(tmp_path)
    out = tmp_path / "emit"
    rc = main(["emit", str(bases), str(out), f"{fixtures}:E"])
    assert rc == 0
    assert main(["diff", str(out), str(out), "--bases", str(bases)]) == 0
