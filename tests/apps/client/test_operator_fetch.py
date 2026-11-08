"""Tests for the operator's fetch, run-record, and snapshot-context rows."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest

from edgar_sec.apps.client import operator, operator_fetch, operator_run_records
from edgar_sec.apps.client.models import FilingsResult
from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.foundation.runtime.interactive import MenuAction
from edgar_sec.foundation.serialization import canonical_json


def _acc(number: int) -> str:
    return f"{number:010d}-24-{number:06d}"


def _result(tmp_path: Path, rows: list[tuple[int, str]], **overrides) -> FilingsResult:
    cik = Cik.from_raw(320193)
    items = tuple(
        FilingAggregate(
            accession=AccessionNumber.from_any(_acc(number)),
            primary_cik=cik,
            ciks=(cik,),
            form=form,
            filing_date=f"2024-01-{number:02d}",
        )
        for number, form in rows
    )
    values = {
        "run_id": "run-x",
        "plan_id": "plan-x",
        "target_parquet_glob": "",
        "run_state_sqlite_path": tmp_path / "state.sqlite",
        "artifacts_root": tmp_path,
        "items": items,
    }
    values.update(overrides)
    return FilingsResult(**values)


class _FakeConsole:
    def __init__(self, snapshots=(), tags=(), branches=None, current=None):
        self._snapshots = [dict(item) for item in snapshots]
        self._tags = [dict(item) for item in tags]
        self._branches = dict(branches or {})
        self._current = current

    def list(self):
        return [dict(item) for item in self._snapshots]

    def tags(self):
        return [dict(item) for item in self._tags]

    def branches(self):
        return dict(self._branches)

    def current(self, branch: str = "main"):
        return self._current if branch == "main" else None


def _populated_console() -> _FakeConsole:
    return _FakeConsole(
        snapshots=[
            {"snapshot_id": "snap-1", "kind": "checkpoint", "created_at": "2026-11-01"}
        ],
        tags=[{"name": "v1", "snapshot_id": "snap-1", "created_at": "2026-11-02"}],
        branches={"main": "snap-1"},
        current="snap-1",
    )


class _FakeFacade:
    def __init__(
        self,
        tmp_path,
        fetch_result=None,
        snapshot_result=None,
        stats=None,
        console=None,
    ):
        self.artifacts_root = tmp_path
        self.calls: list = []
        self.fetch_result = fetch_result
        self.fetch_error: Exception | None = None
        self.snapshot_result = snapshot_result
        self._stats = list(stats) if stats is not None else [None]
        self._stats_index = 0
        self.snapshots = console if console is not None else _FakeConsole()

    def fetch(self, **kwargs):
        self.calls.append(("fetch", kwargs))
        if self.fetch_error is not None:
            raise self.fetch_error
        if callable(self.fetch_result):
            return self.fetch_result(kwargs)
        return self.fetch_result

    def from_snapshot(self, snapshot="main", **kwargs):
        self.calls.append(("from_snapshot", snapshot, kwargs))
        return self.snapshot_result

    def cache_stats(self):
        index = min(self._stats_index, len(self._stats) - 1)
        self._stats_index += 1
        return self._stats[index]


def _run(op_id: str, session, options: dict | None = None):
    return operator.execute_by_id(op_id, session, options or {})


def _record(session, record_id: str) -> dict:
    record = operator_run_records.read_run_record(session, record_id)
    assert record is not None
    return record


_STATS_BEFORE = {"hits": 1, "misses": 2, "content_cache": {"entries": 3}}
_STATS_AFTER = {"hits": 4, "misses": 2, "content_cache": {"entries": 3}}


def test_registry_contains_fetch_rows() -> None:
    ids = {spec.id for spec in operator_fetch.build_specs()}
    assert ids == {
        "set_read_context",
        "fetch",
        "snapshot_list",
        "snapshot_tags",
        "snapshot_branches",
        "snapshot_current",
        "snapshot_checkout",
    }
    assert ids <= set(operator.REGISTRY)
    assert operator_fetch.SPECS
    assert operator.GATHERERS["fetch"] is operator_fetch._gather_fetch
    effects = {s.id: s.effect for s in operator_fetch.build_specs()}
    assert effects["fetch"] == "external"
    assert effects["set_read_context"] == "moves_position"
    assert effects["snapshot_checkout"] == "moves_position"
    assert effects["snapshot_list"] == "reads_state"


def test_set_read_context_moves_mode_and_snapshot(tmp_path: Path) -> None:
    session = operator.ClientSession(facade=_FakeFacade(tmp_path))
    outcome = _run("set_read_context", session, {"mode": "snapshot", "snapshot": "v2"})
    assert outcome.error_code is None
    assert outcome.data == {"mode": "snapshot", "snapshot": "v2"}
    assert session.read_context.mode == "snapshot"
    assert session.read_context.snapshot == "v2"
    header = operator.render_session_header(session)
    assert "mode: snapshot" in header
    assert "snapshot: v2" in header
    bad = _run("set_read_context", session, {"mode": "turbo"})
    assert bad.error_code == "invalid_options"
    assert session.read_context.mode == "snapshot"


def test_seed_fetch_fast_engine_and_record_contents(tmp_path: Path) -> None:
    result = _result(tmp_path, [(1, "10-K"), (2, "10-Q")])
    facade = _FakeFacade(
        tmp_path, fetch_result=result, stats=[_STATS_BEFORE, _STATS_AFTER]
    )
    session = operator.ClientSession(facade=facade)
    outcome = _run("fetch", session, {"tickers": ["AAPL"], "forms": ["10-K"]})
    assert outcome.error_code is None
    assert outcome.data["engine"] == "fast"
    assert outcome.data["set"] == "main"
    assert outcome.data["count"] == 2
    assert outcome.data["table_counts"]["catalog"] == 2
    assert outcome.data["table_counts"]["payload"] == 2
    assert outcome.data["cache"]["delta"] == {"hits": 3}
    kind, kwargs = facade.calls[0]
    assert kind == "fetch"
    assert kwargs["tickers"] == ("AAPL",)
    assert kwargs["mode"] == "fast"
    assert kwargs["roles"] == ("primary",)
    assert session.sets["main"].result is result
    assert session.sets["main"].accessions == frozenset({_acc(1), _acc(2)})
    record_id = outcome.data["record_id"]
    assert session.last_run_record == record_id
    path = tmp_path / "operator-runs" / f"{record_id}.json"
    raw = path.read_text(encoding="utf-8")
    record = json.loads(raw)
    assert raw == canonical_json(record)
    assert record["record_id"] == record_id
    assert record["operation"] == "fetch"
    assert record["started_at"] and record["finished_at"]
    assert record["options"]["tickers"] == ["AAPL"]
    assert record["options"]["roles"] == ["primary"]
    assert record["selection"]["kind"] == "seed"
    assert record["selection"]["seed"]["forms"] == ["10-K"]
    assert record["engine"] == "fast"
    assert record["mode"] == "fast"
    assert record["cache"]["before"]["hits"] == 1
    assert record["cache"]["after"]["hits"] == 4
    assert record["cache"]["delta"] == {"hits": 3}
    assert record["table_counts"]["catalog"] == 2
    assert record["member_accounting"]["success_count"] == 2
    assert record["member_accounting"]["error_count"] == 0
    assert record["result"] == {
        "run_id": "run-x",
        "plan_id": "plan-x",
        "accession_count": 2,
    }
    assert record["error_code"] is None


def test_fetch_mode_option_updates_context_before_fetch(tmp_path: Path) -> None:
    facade = _FakeFacade(tmp_path, fetch_result=_result(tmp_path, [(1, "10-K")]))
    session = operator.ClientSession(facade=facade)
    outcome = _run("fetch", session, {"forms": ["10-K"], "mode": "pipeline"})
    assert outcome.error_code is None
    assert session.read_context.mode == "pipeline"
    assert facade.calls[0][1]["mode"] == "pipeline"
    assert outcome.data["engine"] == "pipeline"
    bad = _run("fetch", session, {"forms": ["10-K"], "mode": "turbo"})
    assert bad.error_code == "invalid_options"


def test_engine_reflects_routing_not_declaration(tmp_path: Path) -> None:
    facade = _FakeFacade(tmp_path, fetch_result=_result(tmp_path, [(1, "10-K")]))
    session = operator.ClientSession(facade=facade)
    outcome = _run("fetch", session, {"accessions": [_acc(1)]})
    assert outcome.error_code is None
    assert outcome.data["engine"] == "pipeline"
    assert _record(session, outcome.data["record_id"])["engine"] == "pipeline"
    roles = _run(
        "fetch", session, {"tickers": ["AAPL"], "roles": ["primary", "ex-101"]}
    )
    assert roles.data["engine"] == "pipeline"


def test_engine_follows_result_run_identity(tmp_path: Path) -> None:
    result = _result(
        tmp_path, [(1, "10-K")], run_id="snapshot-snap-9", snapshot_id="snap-9"
    )
    facade = _FakeFacade(tmp_path, fetch_result=result)
    session = operator.ClientSession(facade=facade)
    outcome = _run("fetch", session, {"tickers": ["AAPL"]})
    assert outcome.data["engine"] == "snapshot"
    assert _record(session, outcome.data["record_id"])["engine"] == "snapshot"


def test_fetch_cache_absent_when_stats_unavailable(tmp_path: Path) -> None:
    facade = _FakeFacade(
        tmp_path, fetch_result=_result(tmp_path, [(1, "10-K")]), stats=[None]
    )
    session = operator.ClientSession(facade=facade)
    outcome = _run("fetch", session, {"forms": ["10-K"]})
    assert outcome.error_code is None
    assert outcome.data["cache"] is None
    assert _record(session, outcome.data["record_id"])["cache"] is None


def test_seed_fetch_refusal_binds_without_facade_call(tmp_path: Path) -> None:
    facade = _FakeFacade(tmp_path)
    session = operator.ClientSession(facade=facade)
    for options in ({}, {"limit": 5}, {"roles": ["ex-101"]}):
        outcome = _run("fetch", session, options)
        assert outcome.error_code == "refused"
    assert facade.calls == []
    assert not (tmp_path / "operator-runs").exists()


def test_set_fetch_member_failure_beside_successes(tmp_path: Path) -> None:
    returned = _result(tmp_path, [(1, "10-K"), (2, "10-Q")])
    facade = _FakeFacade(tmp_path, fetch_result=returned)
    session = operator.ClientSession(facade=facade)
    session.add_set("work", [_acc(1), _acc(2), _acc(3)])
    outcome = _run("fetch", session, {})
    assert outcome.error_code is None
    assert facade.calls[0][1]["accessions"] == (_acc(1), _acc(2), _acc(3))
    accounting = outcome.data["member_accounting"]
    assert accounting["success_count"] == 2
    assert accounting["successes"] == [_acc(1), _acc(2)]
    assert accounting["errors"] == [
        {
            "accession": _acc(3),
            "error_code": "external_failure",
            "outcome": "not_returned",
        }
    ]
    assert accounting["error_count"] == 1
    assert session.sets["work"].accessions == frozenset({_acc(1), _acc(2)})
    assert session.sets["work"].result is returned
    record = _record(session, outcome.data["record_id"])
    assert record["selection"] == {
        "kind": "set",
        "set_name": "work",
        "accessions": [_acc(1), _acc(2), _acc(3)],
    }
    assert record["member_accounting"] == accounting
    assert record["engine"] == "pipeline"


class _StubResult:
    """A FilingsResult-shaped stub carrying a payload failure row."""

    run_id = "run-stub"
    plan_id = "plan-stub"
    snapshot_backed = False
    snapshot_id = None

    def to_arrow(self):
        return pa.table(
            {
                "accession": [_acc(1), _acc(2)],
                "form": ["10-K", "10-K"],
                "filing_date": ["2024-01-01", "2024-01-02"],
            }
        )

    def staged_df(self):
        return pd.DataFrame(
            {"accession": [_acc(1), _acc(2)], "outcome": ["acquired", "failed"]}
        )


def test_payload_outcome_failure_is_coded_beside_success(tmp_path: Path) -> None:
    facade = _FakeFacade(tmp_path, fetch_result=_StubResult())
    session = operator.ClientSession(facade=facade)
    outcome = _run("fetch", session, {"accessions": [_acc(1), _acc(2)]})
    assert outcome.error_code is None
    accounting = outcome.data["member_accounting"]
    assert accounting["success_count"] == 1
    assert accounting["successes"] == [_acc(1)]
    assert accounting["errors"] == [
        {"accession": _acc(2), "error_code": "external_failure", "outcome": "failed"}
    ]
    assert outcome.data["table_counts"] == {"catalog": 2, "payload": 2}


def test_facade_failure_returns_external_failure_and_records(tmp_path: Path) -> None:
    facade = _FakeFacade(tmp_path, stats=[_STATS_BEFORE, _STATS_AFTER])
    facade.fetch_error = RuntimeError("boom")
    session = operator.ClientSession(facade=facade)
    outcome = _run("fetch", session, {"forms": ["10-K"]})
    assert outcome.error_code == "external_failure"
    assert outcome.data["record_id"] == session.last_run_record
    record = _record(session, session.last_run_record)
    assert record["error_code"] == "external_failure"
    assert record["error"] == "boom"
    assert record["table_counts"] == {}
    assert record["member_accounting"]["success_count"] == 0
    listing = _run("past_runs", session, {})
    assert listing.total == 1
    assert listing.data["records"][0]["error_count"] == 0


def test_past_runs_list_inspect_and_bounds(tmp_path: Path) -> None:
    facade = _FakeFacade(tmp_path, fetch_result=_result(tmp_path, [(1, "10-K")]))
    session = operator.ClientSession(facade=facade)
    empty = _run("past_runs", session, {})
    assert empty.error_code == "absent"
    assert empty.data["present"] is False
    first = _run("fetch", session, {"forms": ["10-K"]})
    second = _run("fetch", session, {"forms": ["10-Q"]})
    listing = _run("past_runs", session, {})
    assert listing.error_code is None
    assert (listing.total, listing.shown) == (2, 2)
    assert listing.data["present"] is True
    bounded = _run("past_runs", session, {"limit": 1})
    assert (bounded.total, bounded.shown) == (2, 1)
    assert _run("past_runs", session, {"limit": 0}).error_code == "invalid_options"
    inspected = _run("inspect_past_run", session, {})
    assert inspected.error_code is None
    assert inspected.data["record_id"] == second.data["record_id"]
    assert inspected.data["member_accounting"]["success_count"] == 1
    by_id = _run("inspect_past_run", session, {"record_id": first.data["record_id"]})
    assert by_id.data["record_id"] == first.data["record_id"]
    ghost = _run("inspect_past_run", session, {"record_id": "op-ghost"})
    assert ghost.error_code == "not_found"


def test_rerun_set_record_reproduces_selection_exactly(tmp_path: Path) -> None:
    def _dynamic(kwargs):
        present = {_acc(1): "10-K", _acc(2): "10-Q"}
        rows = [(int(a[:10]), present[a]) for a in kwargs["accessions"] if a in present]
        return _result(tmp_path, rows)

    facade = _FakeFacade(tmp_path, fetch_result=_dynamic)
    session = operator.ClientSession(facade=facade)
    session.add_set("work", [_acc(3), _acc(1), _acc(2)])
    original = _run("fetch", session, {})
    record_id = original.data["record_id"]
    fresh = operator.ClientSession(facade=facade)
    rerun = _run("rerun_past_run", fresh, {"record_id": record_id})
    assert rerun.error_code is None
    assert facade.calls[-1][1]["accessions"] == (_acc(1), _acc(2), _acc(3))
    assert fresh.sets["work"].accessions == frozenset({_acc(1), _acc(2)})
    new_record = _record(fresh, rerun.data["record_id"])
    assert new_record["record_id"] != record_id
    assert new_record["operation"] == "rerun_past_run"
    assert new_record["rerun_of"] == record_id
    assert new_record["selection"]["accessions"] == [_acc(1), _acc(2), _acc(3)]
    assert fresh.last_run_record == new_record["record_id"]


def test_rerun_seed_record_repeats_declaration(tmp_path: Path) -> None:
    facade = _FakeFacade(tmp_path, fetch_result=_result(tmp_path, [(1, "10-K")]))
    session = operator.ClientSession(facade=facade)
    original = _run(
        "fetch", session, {"tickers": ["AAPL"], "forms": ["10-K"], "limit": 5}
    )
    record_id = original.data["record_id"]
    rerun = _run("rerun_past_run", session, {"record_id": record_id})
    assert rerun.error_code is None
    kwargs = facade.calls[-1][1]
    assert kwargs["tickers"] == ("AAPL",)
    assert kwargs["forms"] == ("10-K",)
    assert kwargs["limit"] == 5
    new_record = _record(session, rerun.data["record_id"])
    assert new_record["selection"] == _record(session, record_id)["selection"]
    assert (
        _run("rerun_past_run", session, {"record_id": "op-ghost"}).error_code
        == "not_found"
    )


def test_snapshot_absence_renders_as_absence(tmp_path: Path) -> None:
    session = operator.ClientSession(facade=_FakeFacade(tmp_path))
    for op_id in ("snapshot_list", "snapshot_tags", "snapshot_branches"):
        outcome = _run(op_id, session, {})
        assert outcome.error_code == "absent"
        assert outcome.data["present"] is False
        assert outcome.total == 0
        assert json.dumps(outcome.to_payload())
    current = _run("snapshot_current", session, {})
    assert current.error_code == "absent"
    assert current.data["present"] is False
    assert current.data["snapshot"] is None


def test_snapshot_listing_and_checkout_repoints_reads(tmp_path: Path) -> None:
    facade = _FakeFacade(
        tmp_path,
        snapshot_result=_result(tmp_path, [(7, "10-K")]),
        console=_populated_console(),
    )
    session = operator.ClientSession(facade=facade)
    listing = _run("snapshot_list", session, {})
    assert listing.error_code is None
    assert (listing.total, listing.shown) == (1, 1)
    assert listing.data["present"] is True
    assert listing.data["snapshots"][0]["snapshot_id"] == "snap-1"
    tags = _run("snapshot_tags", session, {})
    assert tags.data["tags"][0]["name"] == "v1"
    branches = _run("snapshot_branches", session, {})
    assert branches.data["branches"] == {"main": "snap-1"}
    current = _run("snapshot_current", session, {})
    assert current.data == {"branch": "main", "snapshot": "snap-1", "present": True}
    unknown = _run("snapshot_checkout", session, {"selector": "ghost"})
    assert unknown.error_code == "not_found"
    assert session.read_context.snapshot == "main"
    checkout = _run("snapshot_checkout", session, {"selector": "v1"})
    assert checkout.error_code is None
    assert session.read_context.snapshot == "v1"
    assert "snapshot: v1" in operator.render_session_header(session)
    seeded = _run("seed_snapshot", session, {"forms": ["10-K"]})
    assert seeded.error_code is None
    kind, snapshot, _kwargs = facade.calls[-1]
    assert (kind, snapshot) == ("from_snapshot", "v1")


def test_snapshot_checkout_by_id_and_fetch_uses_context(tmp_path: Path) -> None:
    facade = _FakeFacade(
        tmp_path,
        fetch_result=_result(
            tmp_path, [(1, "10-K")], run_id="snapshot-snap-1", snapshot_id="snap-1"
        ),
        console=_populated_console(),
    )
    session = operator.ClientSession(facade=facade)
    assert _run("snapshot_checkout", session, {"selector": "snap-1"}).error_code is None
    _run("set_read_context", session, {"mode": "snapshot"})
    outcome = _run("fetch", session, {"forms": ["10-K"]})
    assert outcome.error_code is None
    assert facade.calls[-1][1]["snapshot"] == "snap-1"
    assert outcome.data["engine"] == "snapshot"


def _fake_prompt(answers: dict[str, str]):
    def prompt(prompt: str, default: str = "") -> str:
        for key, value in answers.items():
            if prompt.startswith(key):
                return value
        return default

    return prompt


def test_gather_fetch_echoes_resolved_dates_and_confirms(monkeypatch, capsys) -> None:
    answers = {"tickers": "AAPL", "forms": "10-K", "dates": "2024", "limit": "none"}
    monkeypatch.setattr(operator_fetch, "prompt_text", _fake_prompt(answers))
    monkeypatch.setattr(
        operator_fetch, "prompt_confirm", lambda prompt, default=False: True
    )
    session = operator.ClientSession(facade=_FakeFacade(Path("/tmp")))
    options = operator_fetch.GATHERERS["fetch"](session)
    assert options.tickers == ("AAPL",)
    assert options.forms == ("10-K",)
    assert options.limit is None
    assert options.dates == "2024"
    out = capsys.readouterr().out
    assert "Resolved fetch selection" in out
    assert "dates resolved" in out
    assert "2024" in out


def test_gather_fetch_declined_confirmation_runs_nothing(monkeypatch) -> None:
    monkeypatch.setattr(operator_fetch, "prompt_text", _fake_prompt({"forms": "10-K"}))
    monkeypatch.setattr(
        operator_fetch, "prompt_confirm", lambda prompt, default=False: False
    )
    session = operator.ClientSession(facade=_FakeFacade(Path("/tmp")))
    with pytest.raises(RuntimeError):
        operator_fetch.GATHERERS["fetch"](session)


def test_menu_fetch_action_gathers_then_executes(tmp_path: Path, monkeypatch) -> None:
    facade = _FakeFacade(tmp_path, fetch_result=_result(tmp_path, [(1, "10-K")]))
    session = operator.ClientSession(facade=facade)
    monkeypatch.setattr(operator_fetch, "prompt_text", _fake_prompt({"forms": "10-K"}))
    monkeypatch.setattr(
        operator_fetch, "prompt_confirm", lambda prompt, default=False: True
    )
    menu = operator.build_operator_menu(session)
    action = next(
        item
        for item in menu
        if isinstance(item, MenuAction) and item.label == "Fetch filings"
    )
    action.callback()
    assert facade.calls[0][1]["forms"] == ("10-K",)
    assert session.sets["main"].accessions == frozenset({_acc(1)})
    assert session.last_run_record
