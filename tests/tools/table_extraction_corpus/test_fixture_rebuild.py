"""Fixture rebuild: matching, spec derivation, two-stage account."""

from __future__ import annotations

import json
from pathlib import Path

from edgar_sec.tools.table_extraction_corpus import fixture_rebuild
from edgar_sec.tools.table_extraction_corpus.fixture_rebuild import (
    cell_set,
    load_specimens,
    match_members,
    norm_cell,
    specimen_jobs,
    stage_aggregate,
    stage_cure,
)

A1 = "0000000123-20-000001"
A2 = "0000000456-21-000002"
A9 = "0000000789-19-000003"
TARGET1 = [["alpha", "bravo"], ["charlie", "delta"], ["echo", "foxtrot"]]
TARGET2 = [["golf", "hotel"], ["india", "juliett"]]


def test_norm_cell_and_cell_set():
    assert norm_cell(" Total Assets ($000s) ") == "totalassets000s"
    assert cell_set([["alpha", "no", "bravo"], None]) == {"alpha", "bravo"}
    assert cell_set(None) == set()


def test_targets_loader_forms(tmp_path):
    single = [{"adsh": A1, "rows": TARGET1}, {"adsh": A1, "rows": TARGET2}]
    multi = [{"adsh": A2, "tables": [{"rows": TARGET1}, {"rows": TARGET2}]}]
    (tmp_path / "single.json").write_text(json.dumps(single))
    (tmp_path / "multi.json").write_text(json.dumps(multi))
    assert fixture_rebuild._targets(tmp_path, "single.json") == {A1: [TARGET2]}
    assert fixture_rebuild._targets(tmp_path, "multi.json") == {
        A2: [TARGET1, TARGET2]
    }


def _write_inputs(tmp_path: Path) -> Path:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    adjudication = [
        {
            "adsh": A1,
            "ciks": [123],
            "form": "10-K",
            "file_date": "2020-02-03",
            "file": "doc1.htm",
            "file_used": "ex99.htm",
        },
        {
            "adsh": A2,
            "ciks": [456],
            "form": "10-Q",
            "file_date": "2021-05-06",
            "file": "a2.htm",
        },
    ]
    (inputs / "adjudication.json").write_text(json.dumps(adjudication))
    dump = [
        {"adsh": A1, "rows": TARGET1},
        {"adsh": A2, "rows": TARGET2},
    ]
    (inputs / "tables-dump.json").write_text(json.dumps(dump))
    frame_specs = {
        A9: {
            "cik": "0000000789",
            "form": "10-K",
            "filing_date": "2019-01-01",
            "era": "y2010s",
        }
    }
    (inputs / "frame-specs.json").write_text(json.dumps(frame_specs))
    return inputs


def _specimens() -> dict:
    return {
        "family": "intangibles",
        "stratum": "E",
        "rounds": [
            {
                "adjudication": "adjudication.json",
                "tables": "tables-dump.json",
                "era": "efts-sample",
                "accessions": [A1, A2],
            }
        ],
        "frame": {"specs": "frame-specs.json", "bares": [f"{A9}:3"]},
    }


def test_specimen_jobs_derivation(tmp_path):
    inputs = _write_inputs(tmp_path)
    jobs, round_accessions = specimen_jobs(_specimens(), inputs)
    assert round_accessions == [A1, A2]
    specs = dict(jobs)
    assert specs[A1]["cik"] == "123"
    assert specs[A1]["era"] == "efts-sample"
    assert specs[A9]["cik"] == "0000000789"
    assert specs[A9]["era"] == "y2010s"
    assert [a for a, _ in jobs] == [A1, A2, A9]


def _fixture(tmp_path: Path, accession: str, geometries: list) -> Path:
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir(parents=True, exist_ok=True)
    doc = {"accession": accession, "status": "ok", "geometries": geometries}
    (fixtures / f"{accession}.json").write_text(json.dumps(doc))
    return fixtures


def test_match_members_scores_and_margin(tmp_path):
    geometries = [
        {"table_index": 7, "rows": TARGET1},
        {"table_index": 9, "rows": [["alpha", "bravo", "charlie"]]},
    ]
    fixtures = _fixture(tmp_path, A1, geometries)
    match = match_members(fixtures, {A1: [TARGET1]}, [A1], 5)
    entry = match[A1]
    assert entry["status"] == "matched"
    assert entry["table_index"] == 7
    assert entry["score"] == 1.0
    assert entry["margin"] == 0.5
    assert entry["bare"] == f"{A1}:7"


def test_match_members_statuses(tmp_path):
    fixtures = _fixture(tmp_path, A1, [])
    _fixture(tmp_path, A2, [{"table_index": 1, "rows": TARGET2}])
    match = match_members(fixtures, {A2: [TARGET2]}, [A1, A2], 5)
    assert match[A1] == {"status": "no_dump_or_fixture"}
    assert match[A2] == {"status": "no_scorable_target"}
    fixtures2 = _fixture(tmp_path / "x", A1, [])
    match2 = match_members(fixtures2, {A1: [TARGET1]}, [A1], 5)
    assert match2[A1] == {"status": "no_geometries"}


class _Aggregate:
    primary_document_path = "/Archives/edgar/data/123/x/primary.htm"


def _fake_extract(cured: dict):
    def extract(spec, raw, document_path, *, tree, exhibits=(), stratum=None):
        primary = spec.get("primary_document")
        if primary in cured:
            geometries = cured[primary]
        elif spec["accession"] == A1:
            geometries = [
                {
                    "table_index": 7,
                    "rows": [["alpha", "bravo"], ["charlie", "delta"],
                             ["echo", "zzzzz"]],
                }
            ]
        elif spec["accession"] == A2:
            geometries = [{"table_index": 4, "rows": TARGET2}]
        else:
            geometries = [{"table_index": 3, "rows": [["frame", "table"]]}]
        record = {
            "accession": spec["accession"],
            "status": "ok",
            "geometries": geometries,
        }
        return record, [], {}

    return extract


def _stage_fakes(monkeypatch, cured: dict):
    monkeypatch.setattr(fixture_rebuild, "make_client", lambda workers: object())
    monkeypatch.setattr(
        fixture_rebuild, "build_aggregate", lambda client, spec: (_Aggregate(), "x")
    )
    monkeypatch.setattr(fixture_rebuild, "primary_bytes", lambda agg: b"<html/>")
    monkeypatch.setattr(fixture_rebuild, "extract_filing", _fake_extract(cured))


def test_two_stage_account(tmp_path, monkeypatch):
    cured = {
        "ex99.htm": [{"table_index": 7, "rows": TARGET1}],
        "a2.htm": [{"table_index": 4, "rows": TARGET2}],
    }
    _stage_fakes(monkeypatch, cured)
    inputs = _write_inputs(tmp_path)
    specimens = _specimens()
    work, out = tmp_path / "work", tmp_path / "out"
    summary = stage_aggregate(inputs, specimens, work, out, tree="t0", workers=1)
    assert summary == {
        "fixtures_ok": 3,
        "fixtures_total": 3,
        "matched": 1,
        "weak_matches": 0,
        "bases_members": 2,
    }
    prior = json.loads((out / "match-report.json").read_text())
    assert prior[A1]["score"] == 0.833
    assert prior[A2] == {"status": "no_scorable_target"}

    class _Client:
        def get_bytes(self, url):
            return b"<html/>"

    monkeypatch.setattr(fixture_rebuild, "make_client", lambda workers: _Client())
    cure = stage_cure(inputs, specimens, work, out, tree="t0", prior_match=prior)
    assert cure["rebuilt"] == 2
    assert cure["matched"] == 2
    assert cure["still_weak_or_unmatched"] == {}
    assert cure["bases_members"] == 3
    bases = json.loads((out / "bases.json").read_text())
    ids = [r["specimen_id"] for r in bases["members"]["E"]["intangibles"]]
    assert ids == [f"{A9}:3", f"{A1}:7", f"{A2}:4"]
    rows = json.loads((out / "matched-rows.json").read_text())
    assert set(rows) == {A1, A2}


def test_rebuild_summary_and_cli(tmp_path, monkeypatch, capsys):
    cured = {
        "ex99.htm": [{"table_index": 7, "rows": TARGET1}],
        "a2.htm": [{"table_index": 4, "rows": TARGET2}],
    }
    _stage_fakes(monkeypatch, cured)

    class _Client:
        def get_bytes(self, url):
            return b"<html/>"

    monkeypatch.setattr(fixture_rebuild, "make_client", lambda workers: _Client())
    inputs = _write_inputs(tmp_path)
    specimens_path = tmp_path / "specimens.json"
    specimens_path.write_text(json.dumps(_specimens()))
    assert load_specimens(specimens_path)["family"] == "intangibles"
    rc = fixture_rebuild.main(
        [
            "--inputs", str(inputs),
            "--specimens", str(specimens_path),
            "--work", str(tmp_path / "work"),
            "--out", str(tmp_path / "out"),
            "--tree", "t0",
            "--workers", "1",
        ]
    )
    assert rc == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["fixtures_total"] == 3
    assert printed["geometries_total"] == 3
    assert printed["cure"]["matched"] == 2
