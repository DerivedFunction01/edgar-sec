"""Tests for the fetch CLI argument routing and rendering."""

from __future__ import annotations

import inspect
import json

import pyarrow as pa
import pytest

from edgar_sec.apps.client import cli
from edgar_sec.apps.client.facade import Edgar

_CATALOG_SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("form", pa.string()),
        ("filing_date", pa.string()),
        ("primary_document", pa.string()),
    ]
)


def _rows(count: int) -> list[dict[str, str]]:
    return [
        {
            "accession": f"ACC-{index:02d}",
            "form": "10-K",
            "filing_date": "2024-01-15",
            "primary_document": "primary.htm",
        }
        for index in range(count)
    ]


class _FakeResult:
    run_id = "run-test"
    plan_id = "plan-test"

    def __init__(self, rows: list[dict[str, str]]) -> None:
        self._rows = rows

    def __len__(self) -> int:
        return len(self._rows)

    def to_arrow(self) -> pa.Table:
        return pa.Table.from_pylist(self._rows, schema=_CATALOG_SCHEMA)


def _install_fake(monkeypatch, rows: list[dict[str, str]] | None = None):
    calls: dict[str, dict[str, object]] = {}
    result = _FakeResult(_rows(2) if rows is None else rows)

    class FakeEdgar:
        def fetch(self, **kwargs: object) -> _FakeResult:
            calls["fetch"] = kwargs
            return result

        def fetch_from_file(self, **kwargs: object) -> _FakeResult:
            calls["fetch_from_file"] = kwargs
            return result

    monkeypatch.setattr(cli, "Edgar", FakeEdgar)
    return calls


def test_fetch_kwargs_pin_against_signature(monkeypatch) -> None:
    calls = _install_fake(monkeypatch)
    argv = [
        "--forms",
        "10-K",
        "--ciks",
        "320193",
        "--tickers",
        "AAPL",
        "--accessions",
        "0000320193-23-000106",
        "--dates",
        "2024",
        "--suffixes",
        "htm",
        "--roles",
        "primary",
        "--limit",
        "5",
        "--operation",
        "raw",
        "--mode",
        "pipeline",
        "--snapshot",
        "main",
    ]
    assert cli.main(argv) == 0
    kwargs = calls["fetch"]
    signature = inspect.signature(Edgar.fetch)
    signature.bind(object(), **kwargs)
    assert "role" not in kwargs
    assert kwargs == {
        "forms": ("10-K",),
        "ciks": ("320193",),
        "tickers": ("AAPL",),
        "accessions": ("0000320193-23-000106",),
        "dates": "2024",
        "suffixes": ("htm",),
        "roles": ("primary",),
        "limit": 5,
        "operation": "raw",
        "mode": "pipeline",
        "snapshot": "main",
    }


def test_fetch_defaults_match_facade_defaults(monkeypatch) -> None:
    calls = _install_fake(monkeypatch)
    assert cli.main([]) == 0
    kwargs = calls["fetch"]
    parameters = inspect.signature(Edgar.fetch).parameters
    assert kwargs["roles"] == parameters["roles"].default
    assert kwargs["mode"] == parameters["mode"].default
    assert kwargs["snapshot"] == parameters["snapshot"].default
    assert kwargs["forms"] == ()
    assert kwargs["limit"] is None


def test_fast_mode_routes_fast(monkeypatch, capsys) -> None:
    calls = _install_fake(monkeypatch)
    argv = ["--mode", "fast", "--ciks", "320193", "--forms", "10-K", "--json"]
    assert cli.main(argv) == 0
    assert calls["fetch"]["mode"] == "fast"
    payload = json.loads(capsys.readouterr().out)
    assert payload["engine"] == "fast"
    assert payload["accession_count"] == 2
    assert "status" not in payload


def test_pipeline_mode_routes_pipeline(monkeypatch, capsys) -> None:
    calls = _install_fake(monkeypatch)
    assert cli.main(["--mode", "pipeline", "--ciks", "320193", "--json"]) == 0
    assert calls["fetch"]["mode"] == "pipeline"
    payload = json.loads(capsys.readouterr().out)
    assert payload["engine"] == "pipeline"


def test_snapshot_mode_routes_snapshot(monkeypatch, capsys) -> None:
    calls = _install_fake(monkeypatch)
    argv = ["--mode", "snapshot", "--snapshot", "v1", "--forms", "10-K", "--json"]
    assert cli.main(argv) == 0
    assert calls["fetch"]["mode"] == "snapshot"
    assert calls["fetch"]["snapshot"] == "v1"
    payload = json.loads(capsys.readouterr().out)
    assert payload["engine"] == "snapshot"
    assert payload["snapshot"] == "v1"


def test_fast_with_non_primary_role_routes_pipeline(monkeypatch, capsys) -> None:
    calls = _install_fake(monkeypatch)
    argv = ["--mode", "fast", "--roles", "EX-99.1", "--accessions", "A1", "--json"]
    assert cli.main(argv) == 0
    assert calls["fetch"]["roles"] == ("EX-99.1",)
    payload = json.loads(capsys.readouterr().out)
    assert payload["engine"] == "pipeline"


def test_fast_with_accessions_routes_pipeline(monkeypatch, capsys) -> None:
    _install_fake(monkeypatch)
    argv = ["--mode", "fast", "--accessions", "0000320193-23-000106", "--json"]
    assert cli.main(argv) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["engine"] == "pipeline"


def test_file_routes_to_fetch_from_file(monkeypatch, capsys) -> None:
    calls = _install_fake(monkeypatch)
    argv = ["--file", "targets.csv", "--forms", "10-K", "--roles", "primary", "--json"]
    assert cli.main(argv) == 0
    assert "fetch" not in calls
    kwargs = calls["fetch_from_file"]
    inspect.signature(Edgar.fetch_from_file).bind(object(), **kwargs)
    assert kwargs == {
        "file_path": "targets.csv",
        "forms": ("10-K",),
        "roles": ("primary",),
        "operation": "raw",
    }
    payload = json.loads(capsys.readouterr().out)
    assert payload["engine"] == "pipeline"


def test_render_summary_is_bounded(monkeypatch, capsys) -> None:
    _install_fake(monkeypatch, rows=_rows(25))
    assert cli.main(["--ciks", "320193"]) == 0
    out = capsys.readouterr().out
    assert "Engine: fast" in out
    assert "Showing 10 of 25 accessions" in out
    assert "ACC-09" in out
    assert "ACC-24" not in out
    assert "... and 15 more (not shown)" in out


def test_render_summary_empty_result(monkeypatch, capsys) -> None:
    _install_fake(monkeypatch, rows=[])
    assert cli.main(["--ciks", "320193"]) == 0
    out = capsys.readouterr().out
    assert "Acquired 0 accessions" in out
    assert "Showing 0 of 0 accessions" in out


def test_singular_role_flag_is_rejected(monkeypatch) -> None:
    _install_fake(monkeypatch)
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--role", "primary"])
    assert excinfo.value.code == 2
