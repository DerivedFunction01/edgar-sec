"""Section corpus banking: one specimen end to end from a local body."""

from __future__ import annotations

import json
from pathlib import Path

from edgar_sec.tools.section_corpus.build import bank_specimen
from tests.support import fixture_path

_JOB = {
    "slug": "control_18k",
    "form": "18-K/A",
    "accession": "0001104659-26-117215",
    "document": "tm2627716d1_18ka.htm",
    "era": "2026",
}


def test_bank_specimen_reproduces_the_committed_corpus_entry(
    tmp_path: Path,
) -> None:
    body = fixture_path(
        "document/form_18k/0001104659-26-117215__tm2627716d1_18ka.htm"
    ).read_bytes()
    record = bank_specimen(tmp_path, _JOB, body)

    corpus = fixture_path("engine/forms/sections/section_corpus")
    committed = next(
        e
        for e in json.loads((corpus / "index.json").read_text(encoding="utf-8"))
        if e["id"] == record["id"]
    )
    assert record["baseline"] == committed["baseline"]
    assert record["toc_span"] == committed["toc_span"]
    banked_text = (tmp_path / record["text"]).read_text(encoding="utf-8")
    committed_text = (corpus / committed["text"]).read_text(encoding="utf-8")
    assert banked_text == committed_text


def test_bank_specimen_writes_index_and_taxonomy(tmp_path: Path) -> None:
    body = fixture_path(
        "document/form_18k/0001104659-26-117215__tm2627716d1_18ka.htm"
    ).read_bytes()
    record = bank_specimen(tmp_path, _JOB, body)

    index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert [e["id"] for e in index] == [record["id"]]
    taxonomies = json.loads((tmp_path / "taxonomies.json").read_text(encoding="utf-8"))
    assert taxonomies["control_18k"]
    assert record["expected"] == record["baseline"]
