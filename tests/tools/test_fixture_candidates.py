"""Offline tests for the fixture-candidate gathering tool."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

import edgar_sec.tools.fixture_candidates as fixture_candidates
from edgar_sec.infra.sec_http.errors import PermanentHttpError, RetryExhausted
from edgar_sec.tools.fixture_candidates import (
    _instance_name,
    _score_candidate,
    build_registry,
    count_facts,
    load_config,
)

_INLINE = (
    b'<html><ix:nonNumeric name="us-gaap:Revenues" contextRef="c1">5</ix:nonNumeric>'
    b'<ix:nonFraction name="us-gaap:Assets" contextRef="c1">7</ix:nonFraction>'
    b'<ix:nonNumeric name="dei:EntityRegistrantName" contextRef="c1">X</ix:nonNumeric>'
    b'<ix:nonNumeric name="srt:ProductOrServiceAxis" contextRef="c1">z</ix:nonNumeric></html>'
)
_INSTANCE = (
    b'<xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance">'
    b'<xbrli:context id="c1"/><us-gaap:Revenues>5</us-gaap:Revenues>'
    b"<us-gaap:Assets>7</us-gaap:Assets><dei:Cover>1</dei:Cover></xbrl>"
)


def _record(accession: str, year: int, *, xbrl: bool = True, seed: bool = False):
    return {
        "cik": "0000000001",
        "filer": "Example",
        "accession": accession,
        "form": "8-K/A",
        "filing_date": f"{year}-06-30",
        "period": f"{year}-06-30",
        "is_xbrl": xbrl,
        "is_inline_xbrl": xbrl,
        "primary_document": "doc.htm",
        "archive_url": "https://example.invalid/doc.htm",
        "seed_filer": seed,
        "screen": "8ka-901a",
    }


def test_count_facts_inline_buckets_by_prefix():
    counts = count_facts(_INLINE, inline=True)
    assert counts["total_facts"] == 4
    assert counts["us_gaap_facts"] == 2
    assert counts["dei_facts"] == 1


def test_count_facts_instance_skips_structural_prefixes():
    counts = count_facts(_INSTANCE, inline=False)
    assert counts["total_facts"] == 3
    assert counts["us_gaap_facts"] == 2
    assert counts["dei_facts"] == 1


def test_instance_name_skips_linkbases():
    names = ["a.xsd", "a_lab.xml", "a_pre.xml", "a.xml", "doc.htm"]
    assert _instance_name(names, "doc.htm", inline=False) == "a.xml"
    assert _instance_name(["a.xsd"], "doc.htm", inline=False) is None


def test_instance_name_prefers_extracted_instance_for_inline():
    names = ["doc.htm", "doc_htm.xml", "a.xsd"]
    assert _instance_name(names, "doc.htm", inline=True) == "doc_htm.xml"
    assert _instance_name(["doc.htm"], "doc.htm", inline=True) == "doc.htm"


def test_count_facts_dedupes_identical_facts():
    payload = (
        b'<xbrl><us-gaap:Revenues contextRef="c1">5</us-gaap:Revenues>'
        b'<us-gaap:Revenues contextRef="c1">5</us-gaap:Revenues>'
        b'<us-gaap:Revenues contextRef="c2">5</us-gaap:Revenues>'
        b'<xbrldi:explicitMember dimension="d">m</xbrldi:explicitMember></xbrl>'
    )
    counts = count_facts(payload, inline=False)
    assert counts["total_facts"] == 2
    assert counts["us_gaap_facts"] == 2


def test_registry_filters_floor_and_ranks_seed_first(tmp_path: Path):
    checkpoint = tmp_path / "checkpoints"
    checkpoint.mkdir()
    rows = [
        {
            **_record("acc-plain", 2024),
            "ex101_present": True,
            "total_facts": 900,
            "us_gaap_facts": 800,
            "dei_facts": 40,
            "phrasing_matches": [],
        },
        {
            **_record("acc-seed", 2024, seed=True),
            "ex101_present": True,
            "total_facts": 300,
            "us_gaap_facts": 250,
            "dei_facts": 40,
            "phrasing_matches": [],
        },
        {
            **_record("acc-thin", 2024),
            "ex101_present": True,
            "total_facts": 60,
            "us_gaap_facts": 50,
            "dei_facts": 10,
            "phrasing_matches": [],
        },
    ]
    (checkpoint / "s.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    registry = build_registry(tmp_path, tmp_path / "out.json", screen_name="8ka-901a")
    assert [r["accession"] for r in registry["candidates"]] == [
        "acc-seed",
        "acc-plain",
    ]
    assert registry["scored_candidates"] == 3


def _write_checkpoint(tmp_path: Path, rows: list[dict]) -> None:
    checkpoint = tmp_path / "checkpoints"
    checkpoint.mkdir(exist_ok=True)
    (checkpoint / "s.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )


def test_registry_without_seed_preference_ranks_by_substance(tmp_path: Path):
    rows = [
        {
            **_record("acc-seed", 2024, seed=True),
            "ex101_present": True,
            "total_facts": 300,
            "us_gaap_facts": 250,
            "dei_facts": 40,
            "phrasing_matches": [],
        },
        {
            **_record("acc-plain", 2024),
            "ex101_present": True,
            "total_facts": 900,
            "us_gaap_facts": 800,
            "dei_facts": 40,
            "phrasing_matches": [],
        },
    ]
    _write_checkpoint(tmp_path, rows)
    registry = build_registry(
        tmp_path,
        tmp_path / "out.json",
        screen_name="8ka-901a",
        prefer_seed=False,
    )
    assert [r["accession"] for r in registry["candidates"]] == [
        "acc-plain",
        "acc-seed",
    ]
    assert registry["seed_filer_preference"] is False


class _StubClient:
    def __init__(
        self,
        *,
        package: bytes | None = None,
        package_error: Exception | None = None,
        index_names: list[str] | None = None,
        instance: bytes = b"",
        text: str = "",
    ):
        self.package = package
        self.package_error = package_error
        self.index_names = index_names or []
        self.instance = instance
        self.text = text
        self.urls: list[str] = []

    def get_bytes(self, url: str) -> bytes:
        self.urls.append(url)
        if url.endswith("-xbrl.zip"):
            if self.package_error is not None:
                raise self.package_error
            assert self.package is not None
            return self.package
        return self.instance

    def get_json(self, url: str) -> dict:
        self.urls.append(url)
        return {"directory": {"item": [{"name": n} for n in self.index_names]}}

    def get_text(self, url: str) -> str:
        self.urls.append(url)
        return self.text


def _package(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def _score(monkeypatch, client: _StubClient, record: dict, acquisition: str) -> dict:
    monkeypatch.setattr(fixture_candidates, "_CLIENT", client)
    return _score_candidate((record, ("Item 9.01(a)",), 200, acquisition))


def test_score_via_package_counts_the_instance_member(monkeypatch):
    package = _package(
        {
            "a_ref.xml": b"<linkbase/>",
            "a.xsd": b"<schema/>",
            "a_lab.xml": b"<linkbase/>",
            "a.xml": _INSTANCE,
        }
    )
    client = _StubClient(package=package, text="see Item 9.01(a) here")
    record = _record("0000000001-23-000001", 2023)
    record["is_inline_xbrl"] = False
    row = _score(monkeypatch, client, record, "package")
    assert row["error"] is None
    assert row["source_path"] == "package"
    assert row["ex101_present"] is True
    assert row["total_facts"] == 3
    assert row["us_gaap_facts"] == 2
    assert row["phrasing_matches"] == ["Item 9.01(a)"]


def test_score_via_package_prefers_the_extracted_instance(monkeypatch):
    package = _package({"doc_htm.xml": _INSTANCE, "a.xsd": b"<schema/>"})
    client = _StubClient(package=package, text="plain text")
    row = _score(monkeypatch, client, _record("0000000001-23-000001", 2023), "package")
    assert row["source_path"] == "package"
    assert row["total_facts"] == 3


def test_score_package_absent_scores_no_instance_without_an_index_fetch(monkeypatch):
    error = PermanentHttpError("u", "HTTP 404", 404)
    client = _StubClient(package_error=error)
    row = _score(monkeypatch, client, _record("0000000001-23-000001", 2023), "package")
    assert row["error"] is None
    assert row["source_path"] == "package-absent"
    assert row["total_facts"] is None
    assert row["ex101_present"] is False
    assert not any("index.json" in url for url in client.urls)


def test_score_package_throttle_is_an_error_never_absence(monkeypatch):
    error = RetryExhausted("u", "server error 503", 503)
    client = _StubClient(package_error=error)
    row = _score(monkeypatch, client, _record("0000000001-23-000001", 2023), "package")
    assert row["error"] is not None
    assert row["source_path"] is None


def test_score_index_mode_agrees_with_package_mode(monkeypatch):
    names = ["a.xsd", "a_lab.xml", "a_ref.xml", "a.xml"]
    record = _record("0000000001-23-000001", 2023)
    record["is_inline_xbrl"] = False
    index_client = _StubClient(
        index_names=names, instance=_INSTANCE, text="see Item 9.01(a) here"
    )
    index_row = _score(monkeypatch, index_client, record, "index")
    package_client = _StubClient(
        package=_package(
            {name: _INSTANCE if name == "a.xml" else b"<x/>" for name in names}
        ),
        text="see Item 9.01(a) here",
    )
    package_row = _score(monkeypatch, package_client, record, "package")
    assert index_row["source_path"] == "index"
    assert package_row["source_path"] == "package"
    for key in ("ex101_present", "total_facts", "us_gaap_facts", "phrasing_matches"):
        assert index_row[key] == package_row[key]


def test_load_config_acquisition_modes(tmp_path: Path):
    def write(payload: dict) -> Path:
        path = tmp_path / "config.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    screens = [{"name": "x", "required_item": "9.01"}]
    assert load_config(write({"screens": screens}))["acquisition"] == "package"
    explicit = load_config(write({"screens": screens, "acquisition": "index"}))
    assert explicit["acquisition"] == "index"
    with pytest.raises(ValueError, match="acquisition"):
        load_config(write({"screens": screens, "acquisition": "smoke-signals"}))


def test_load_config_fills_defaults(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"screens": [{"name": "x", "required_item": "9.01"}]}),
        encoding="utf-8",
    )
    config = load_config(path)
    assert config["sample_size"] is None
    assert config["floor_us_gaap_facts"] == 200
    assert config["seed_filer_preference"] is True
    assert config["outputs"]["registry"] == "fixture-candidates-{screen}.json"
