"""Tests for the operator's config-file loader and its two hosts."""

from __future__ import annotations

import json
from pathlib import Path

from edgar_sec.apps.client import operator, operator_config
from edgar_sec.apps.client.models import FilingsResult
from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.forms.sections.models import (
    CandidateKind,
    ResolvedSection,
    SectionSequence,
)
from edgar_sec.foundation.runtime.interactive import MenuAction
from edgar_sec.foundation.runtime.settings import resolve_settings
from tests.support import fixture_path

ACC1 = "0000320193-24-000001"
ACC2 = "0000320193-24-000002"
ACC3 = "0000320193-24-000003"
SECTION_TEXTS = {
    "ITEM 1": "ITEM 1. BUSINESS\nBusiness lead.\n\nBusiness details block.\n",
    "ITEM 1A": "ITEM 1A. RISK FACTORS\nRisk lead.\n\nRisk details block.\n",
}


def _section(item: str, title: str, start: int) -> ResolvedSection:
    return ResolvedSection(
        item_identifier=item,
        start_line=start,
        end_line=start + 2,
        title=title,
        raw_heading=item,
        kind=CandidateKind.STANDARD,
        confidence=1.0,
    )


def _aggregate(accession: str, form: str) -> FilingAggregate:
    cik = Cik.from_raw(320193)
    return FilingAggregate(
        accession=AccessionNumber.from_any(accession),
        primary_cik=cik,
        ciks=(cik,),
        form=form,
        filing_date="2024-01-02",
    )


def _result(tmp_path: Path, pairs: list[tuple[str, str]]) -> FilingsResult:
    return FilingsResult(
        run_id="run-x",
        plan_id="plan-x",
        target_parquet_glob="",
        run_state_sqlite_path=tmp_path / "state.sqlite",
        artifacts_root=tmp_path,
        items=tuple(_aggregate(accession, form) for accession, form in pairs),
    )


class _FakeConsole:
    def list(self):
        return [{"snapshot_id": "snap-1", "kind": "checkpoint", "created_at": "x"}]

    def tags(self):
        return [{"name": "v1", "snapshot_id": "snap-1", "created_at": "x"}]

    def branches(self):
        return {"main": "snap-1"}

    def current(self, branch: str = "main"):
        return "snap-1" if branch == "main" else None


class _FakeFacade:
    def __init__(self, tmp_path: Path) -> None:
        self.artifacts_root = tmp_path
        self.tmp_path = tmp_path
        self.calls: list = []
        self.snapshots = _FakeConsole()

    def fetch(self, **kwargs):
        self.calls.append(("fetch", kwargs))
        if "10-Q" in tuple(kwargs.get("forms") or ()):
            return _result(self.tmp_path, [(ACC2, "10-Q"), (ACC3, "10-Q")])
        return _result(self.tmp_path, [(ACC1, "10-K"), (ACC2, "10-K")])

    def from_snapshot(self, snapshot="main", **kwargs):
        self.calls.append(("from_snapshot", snapshot, kwargs))
        return _result(self.tmp_path, [(ACC1, "10-K")])

    def cache_stats(self):
        return {"hits": 1}

    def sections(self, filing, text=None):
        return SectionSequence(
            family=filing.form,
            sections=(
                _section("ITEM 1", "Business", 3),
                _section("ITEM 1A", "Risk", 6),
            ),
        )

    def section(self, filing, item, text=None):
        found = self.sections(filing).get(item)
        return SECTION_TEXTS[found.item_identifier] if found else ""


def _session(tmp_path: Path, **kwargs) -> operator.ClientSession:
    return operator.ClientSession(facade=_FakeFacade(tmp_path), **kwargs)


def _write(tmp_path: Path, payload, name: str = "config.json") -> Path:
    path = tmp_path / name
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _example_path() -> Path:
    return fixture_path("client/operator_probe_config.json")


def test_registry_contains_load_config_row() -> None:
    assert "load_config" in operator.REGISTRY
    spec = operator.REGISTRY["load_config"]
    assert spec.effect == "reads_state"
    assert spec.result_kind == "key_value"
    assert operator_config.SPECS
    assert operator.GATHERERS["load_config"] is operator_config._gather_load_config


def test_example_config_executes_end_to_end(tmp_path: Path) -> None:
    session = _session(tmp_path)
    run = operator_config.run_config_path(session, _example_path())
    assert run.ok, run.error_message
    assert [result.error_code for result in run.set_results] == [None]
    assert [result.error_code for result in run.operation_results] == [None] * 4
    assert session.read_context.mode == "snapshot"
    assert session.read_context.snapshot == "v1"
    assert session.workers == 2
    assert run.session_values == {"mode": "snapshot", "snapshot": "main", "workers": 2}
    assert run.session_sources == {
        "mode": "config",
        "snapshot": "config",
        "workers": "config",
    }
    assert session.sets["probe"].accessions == frozenset({ACC1, ACC2})
    assert session.current_filing is not None
    assert session.current_filing.accession == ACC1
    read = run.operation_results[-1]
    assert read.data["text"] == SECTION_TEXTS["ITEM 1A"]
    fetch_calls = [call for call in session.facade.calls if call[0] == "fetch"]
    assert len(fetch_calls) == 2
    assert fetch_calls[0][1]["mode"] == "snapshot"
    assert fetch_calls[0][1]["snapshot"] == "main"
    assert fetch_calls[1][1]["accessions"] == (ACC1, ACC2)
    assert fetch_calls[1][1]["snapshot"] == "v1"
    assert fetch_calls[1][1]["workers"] == 2
    records = list((tmp_path / "operator-runs").glob("*.json"))
    assert len(records) == 1
    record = json.loads(records[0].read_text(encoding="utf-8"))
    assert record["operation"] == "fetch"
    assert record["selection"]["accessions"] == [ACC1, ACC2]
    assert session.last_run_record == record["record_id"]


def test_example_config_through_argv_host_json(tmp_path: Path, capsys) -> None:
    session = _session(tmp_path)
    argv = ["--config", str(_example_path()), "--json"]
    assert operator.main(argv, session=session) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["error_code"] is None
    assert payload["session"]["mode"] == "snapshot"
    assert len(payload["sets"]) == 1
    assert len(payload["operations"]) == 4
    assert payload["operations"][-1]["data"]["text"] == SECTION_TEXTS["ITEM 1A"]
    assert list((tmp_path / "operator-runs").glob("*.json"))


def test_unknown_format_version_refuses_before_execution(
    tmp_path: Path, capsys
) -> None:
    path = _write(
        tmp_path,
        {
            "format_version": "2.0",
            "sets": {"probe": {"seed": {"forms": ["10-K"]}}},
            "operations": [{"op": "vars"}],
        },
    )
    session = _session(tmp_path)
    run = operator_config.run_config_path(session, path)
    assert run.error_code == "unsupported_version"
    assert "2.0" in run.error_message
    assert run.operations_declared == 1
    assert session.sets == {}
    assert session.facade.calls == []
    assert operator.main(["--config", str(path), "--json"], session=session) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error_code"] == "unsupported_version"
    assert payload["operations_declared"] == 1
    assert operator.OpResult(kind="object", error_code="unsupported_version")


def test_declared_count_and_error_exits(tmp_path: Path, capsys) -> None:
    session = _session(tmp_path)
    bad = operator_config.run_config_path(session, _write(tmp_path, "{not json"))
    assert bad.operations_declared == 0
    good = _write(tmp_path, {"format_version": "1.0", "operations": []}, name="g.json")
    assert operator.main(["--config", str(good), "--help"], session=session) == 1
    assert operator.main(["--config", str(good), "--bogus"], session=session) == 1
    capsys.readouterr()
    assert operator.main(["--config", str(good)], session=session) == 0
    assert "error_code" not in capsys.readouterr().out


def test_config_error_message_carries_operator_shaped_prose(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {
            "format_version": "1.0",
            "operations": [{"op": "select_filing", "options": {"accession": "A1"}}],
        },
    )
    run = operator_config.run_config_path(_session(tmp_path), path)
    assert run.error_code == "missing_context"
    assert run.error_message == "operation requires selection"
    assert run.to_payload()["message"] == "operation requires selection"


def test_malformed_declarations_refuse_before_execution(tmp_path: Path) -> None:
    cases = [
        {"sets": {"x": {"unionize": ["a", "b"]}}},
        {"operations": [{"op": "no_such_operation"}]},
        {"sets": {"x": {"union": ["ghost", "also_ghost"]}}},
        {
            "sets": {
                "later": {"union": ["early", "early"]},
                "early": {"seed": {"forms": ["10-K"]}},
            }
        },
        {"sets": {"x": {"seed": {"bogus_field": 1}}}},
        {"session": {"mode": "turbo"}},
        {"bogus_top_level": {}},
    ]
    for index, extra in enumerate(cases):
        payload = {"format_version": "1.0", **extra}
        if index == 0:
            payload["sets"] = {
                "good": {"seed": {"forms": ["10-K"]}},
                "x": {"unionize": ["good", "good"]},
            }
            payload["operations"] = [{"op": "vars"}]
        session = _session(tmp_path)
        run = operator_config.run_config_path(session, _write(tmp_path, payload))
        assert run.error_code == "invalid_options", extra
        assert session.sets == {}
        assert session.facade.calls == []


def test_missing_and_malformed_files(tmp_path: Path) -> None:
    session = _session(tmp_path)
    missing = operator_config.run_config_path(session, tmp_path / "ghost.json")
    assert missing.error_code == "not_found"
    bad = operator_config.run_config_path(session, _write(tmp_path, "{not json"))
    assert bad.error_code == "invalid_options"
    no_version = operator_config.run_config_path(
        session, _write(tmp_path, {"operations": []}, name="v.json")
    )
    assert no_version.error_code == "invalid_options"


def test_precedence_mode_and_snapshot_levels(tmp_path: Path) -> None:
    config = _write(
        tmp_path,
        {
            "format_version": "1.0",
            "session": {"mode": "snapshot", "snapshot": "snap-1"},
            "operations": [{"op": "session_summary"}],
        },
    )
    session_default = _session(
        tmp_path,
        read_context=operator.ReadContext(mode="pipeline", snapshot="keep"),
    )
    run = operator_config.run_config_path(session_default, config)
    assert run.ok
    assert run.session_values["mode"] == "snapshot"
    assert run.session_sources["mode"] == "config"
    assert session_default.read_context.snapshot == "snap-1"
    host = _session(
        tmp_path,
        read_context=operator.ReadContext(mode="pipeline", snapshot="keep"),
    )
    run = operator_config.run_config_path(
        host, config, {"mode": "fast", "snapshot": "main"}
    )
    assert run.session_values["mode"] == "fast"
    assert run.session_sources["mode"] == "host"
    assert run.session_sources["snapshot"] == "host"
    assert host.read_context.mode == "fast"
    plain = _write(tmp_path, {"format_version": "1.0", "operations": []}, name="p.json")
    untouched = _session(
        tmp_path,
        read_context=operator.ReadContext(mode="pipeline", snapshot="keep"),
    )
    run = operator_config.run_config_path(untouched, plain)
    assert run.session_values["mode"] == "pipeline"
    assert run.session_sources["mode"] == "session"
    assert run.session_values["snapshot"] == "keep"


def test_precedence_workers_at_each_level(tmp_path: Path) -> None:
    settings_value = int(resolve_settings(include=["runtime"])["runtime.workers"])
    fetch_only = {
        "format_version": "1.0",
        "operations": [{"op": "fetch", "options": {"forms": ["10-K"]}}],
    }

    def last_workers(session) -> int:
        return session.facade.calls[-1][1]["workers"]

    session = _session(tmp_path)
    run = operator_config.run_config_path(session, _write(tmp_path, fetch_only))
    assert run.ok and run.session_sources["workers"] == "settings"
    assert run.session_values["workers"] == settings_value
    assert last_workers(session) == settings_value
    session = _session(tmp_path, workers=7)
    run = operator_config.run_config_path(session, _write(tmp_path, fetch_only))
    assert run.session_sources["workers"] == "session"
    assert last_workers(session) == 7
    configured = dict(fetch_only, session={"workers": 3})
    session = _session(tmp_path, workers=7)
    path = _write(tmp_path, configured)
    run = operator_config.run_config_path(session, path)
    assert run.session_sources["workers"] == "config"
    assert last_workers(session) == 3
    session = _session(tmp_path, workers=7)
    run = operator_config.run_config_path(session, path, {"workers": 5})
    assert run.session_sources["workers"] == "host"
    assert last_workers(session) == 5


def test_argv_host_flags_override_config_session(tmp_path: Path, capsys) -> None:
    path = _write(
        tmp_path,
        {
            "format_version": "1.0",
            "session": {"mode": "snapshot", "snapshot": "snap-1", "workers": 3},
            "operations": [{"op": "session_summary"}],
        },
    )
    session = _session(tmp_path)
    argv = ["--config", str(path), "--mode", "fast", "--snapshot", "main", "--json"]
    assert operator.main(argv, session=session) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["session"]["mode"] == "fast"
    assert payload["session_sources"]["mode"] == "host"
    assert payload["session_sources"]["snapshot"] == "host"
    assert payload["session_sources"]["workers"] == "config"
    assert session.read_context.mode == "fast"


def test_combinator_sets_build_in_declaration_order(tmp_path: Path) -> None:
    payload = {
        "format_version": "1.0",
        "sets": {
            "annual": {"seed": {"forms": ["10-K"]}},
            "quarterly": {"seed": {"forms": ["10-Q"]}},
            "both": {"union": ["annual", "quarterly"]},
            "overlap": {"intersect": ["annual", "quarterly"]},
            "annual_only": {"difference": ["annual", "quarterly"]},
        },
        "operations": [{"op": "vars"}],
    }
    session = _session(tmp_path)
    run = operator_config.run_config_path(session, _write(tmp_path, payload))
    assert run.ok, run.error_message
    assert session.sets["both"].accessions == frozenset({ACC1, ACC2, ACC3})
    assert session.sets["overlap"].accessions == frozenset({ACC2})
    assert session.sets["annual_only"].accessions == frozenset({ACC1})
    assert run.operation_results[0].total == 5


def test_config_seed_refusal_matches_prompted_refusal(tmp_path: Path, capsys) -> None:
    path = _write(
        tmp_path,
        {
            "format_version": "1.0",
            "sets": {"bad": {"seed": {"limit": 5}}},
            "operations": [{"op": "vars"}],
        },
    )
    session = _session(tmp_path)
    run = operator_config.run_config_path(session, path)
    assert run.error_code == "refused"
    assert run.operation_results == ()
    assert session.facade.calls == []
    assert operator.main(["--config", str(path)], session=session) == 1
    assert "refused" in capsys.readouterr().out
    prompted = operator.execute_by_id("seed_query", _session(tmp_path), {"limit": 5})
    assert prompted.error_code == run.error_code
    assert prompted.data["message"] == run.set_results[0].data["message"]


def test_failure_mid_sequence_stops_the_run(tmp_path: Path) -> None:
    payload = {
        "format_version": "1.0",
        "operations": [
            {"op": "fetch", "options": {"forms": ["10-K"]}},
            {"op": "snapshot_checkout", "options": {"selector": "ghost"}},
            {"op": "vars"},
        ],
    }
    session = _session(tmp_path)
    run = operator_config.run_config_path(session, _write(tmp_path, payload))
    assert run.error_code == "not_found"
    assert len(run.operation_results) == 2
    assert run.operation_results[0].error_code is None
    assert run.operation_results[1].error_code == "not_found"
    assert list((tmp_path / "operator-runs").glob("*.json"))


def test_menu_load_config_applies_without_running_operations(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path)
    path = _write(
        tmp_path,
        {
            "format_version": "1.0",
            "session": {"mode": "pipeline"},
            "sets": {"probe": {"seed": {"forms": ["10-K"]}}},
            "operations": [{"op": "fetch", "options": {"forms": ["10-K"]}}],
        },
    )
    result = operator.execute_by_id("load_config", session, {"path": str(path)})
    assert result.error_code is None
    assert result.data["operations_declared"] == 1
    assert result.data["operations_run"] == 0
    assert result.data["sets"] == {"probe": 2}
    assert session.read_context.mode == "pipeline"
    assert session.sets["probe"].accessions == frozenset({ACC1, ACC2})
    assert len(session.facade.calls) == 1
    assert not (tmp_path / "operator-runs").exists()
    labels = [
        item.label
        for item in operator.build_operator_menu(session)
        if isinstance(item, MenuAction)
    ]
    assert "Load config file" in labels
    bad = operator.execute_by_id("load_config", session, {"path": ""})
    assert bad.error_code == "invalid_options"
    ghost = operator.execute_by_id(
        "load_config", session, {"path": str(tmp_path / "ghost.json")}
    )
    assert ghost.error_code == "not_found"
