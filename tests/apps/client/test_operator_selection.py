"""Tests for the operator's selection-building rows."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.apps.client import operator, operator_selection
from edgar_sec.apps.client.models import FilingsResult
from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.foundation.runtime.interactive import MenuAction


def _acc(number: int) -> str:
    return f"{number:010d}-24-{number:06d}"


def _result(tmp_path: Path, rows: list[tuple[int, str]]) -> FilingsResult:
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
    return FilingsResult(
        run_id="run-x",
        plan_id="plan-x",
        target_parquet_glob="",
        run_state_sqlite_path=tmp_path / "state.sqlite",
        artifacts_root=tmp_path,
        items=items,
    )


class _FakeCompany:
    def __init__(self, facade: _FakeFacade) -> None:
        self._facade = facade

    def filings(self, **kwargs):
        self._facade.calls.append(("company_filings", kwargs))
        return self._facade.company_result


class _FakeFacade:
    def __init__(self, fetch_result=None, snapshot_result=None, company_result=None):
        self.calls: list = []
        self.fetch_result = fetch_result
        self.snapshot_result = snapshot_result
        self.company_result = company_result

    def fetch(self, **kwargs):
        self.calls.append(("fetch", kwargs))
        return self.fetch_result

    def from_snapshot(self, snapshot="main", **kwargs):
        self.calls.append(("from_snapshot", snapshot, kwargs))
        return self.snapshot_result

    def company(self, identifier):
        self.calls.append(("company", identifier))
        return _FakeCompany(self)


def _run(op_id: str, session, options: dict | None = None):
    return operator.execute_by_id(op_id, session, options or {})


def _session_with_sets(tmp_path: Path):
    session = operator.ClientSession(facade=_FakeFacade())
    res_a = _result(tmp_path, [(1, "10-K"), (2, "10-Q"), (3, "10-K"), (4, "8-K")])
    res_b = _result(tmp_path, [(3, "10-K"), (4, "8-K"), (5, "10-Q"), (6, "10-K")])
    session.add_set("a", operator_selection.result_accessions(res_a), result=res_a)
    session.add_set("b", operator_selection.result_accessions(res_b), result=res_b)
    return session, res_a, res_b


def test_registry_contains_selection_rows() -> None:
    ids = {row[0] for row in operator_selection._SPEC_ROWS}
    assert ids <= set(operator.REGISTRY)
    assert operator_selection.SPECS
    assert {spec.id for spec in operator_selection.SPECS} == ids
    registry: dict = {}
    operator_selection.register(registry)
    assert set(registry) == ids
    with pytest.raises(ValueError):
        operator_selection.register(registry)


def test_seed_query_uses_session_read_context(tmp_path: Path) -> None:
    result = _result(tmp_path, [(1, "10-K"), (2, "10-Q")])
    facade = _FakeFacade(fetch_result=result)
    session = operator.ClientSession(facade=facade)
    session.read_context.mode = "pipeline"
    session.read_context.snapshot = "v1"
    outcome = _run(
        "seed_query",
        session,
        {"into": "tech", "tickers": ["AAPL"], "forms": ["10-K"], "limit": 5},
    )
    assert outcome.error_code is None
    assert outcome.data == {
        "set": "tech",
        "count": 2,
        "source": "query",
        "mode": "pipeline",
        "snapshot": "v1",
    }
    kind, kwargs = facade.calls[0]
    assert kind == "fetch"
    assert kwargs["tickers"] == ("AAPL",)
    assert kwargs["forms"] == ("10-K",)
    assert kwargs["mode"] == "pipeline"
    assert kwargs["snapshot"] == "v1"
    assert kwargs["limit"] == 5
    assert session.current_set_name == "tech"
    assert session.sets["tech"].result is result
    assert session.sets["tech"].accessions == frozenset({_acc(1), _acc(2)})


def test_seed_query_refusal_binds_without_facade_call() -> None:
    facade = _FakeFacade()
    session = operator.ClientSession(facade=facade)
    for options in ({}, {"limit": 10}, {"into": "x", "limit": 1}):
        outcome = _run("seed_query", session, options)
        assert outcome.error_code == "refused"
        assert json.dumps(outcome.to_payload())
    assert facade.calls == []
    assert session.sets == {}


def test_seed_snapshot_query_and_refusal(tmp_path: Path) -> None:
    result = _result(tmp_path, [(7, "10-K")])
    facade = _FakeFacade(snapshot_result=result)
    session = operator.ClientSession(facade=facade)
    session.read_context.snapshot = "snap1"
    outcome = _run("seed_snapshot", session, {"into": "snap", "forms": ["10-K"]})
    assert outcome.error_code is None
    kind, snapshot, kwargs = facade.calls[0]
    assert (kind, snapshot) == ("from_snapshot", "snap1")
    assert kwargs["forms"] == ("10-K",)
    assert session.sets["snap"].result is result
    for options in ({}, {"limit": 3}):
        assert _run("seed_snapshot", session, options).error_code == "refused"
    assert len(facade.calls) == 1


def test_seed_company_and_refusal(tmp_path: Path) -> None:
    result = _result(tmp_path, [(8, "10-Q")])
    facade = _FakeFacade(company_result=result)
    session = operator.ClientSession(facade=facade)
    outcome = _run(
        "seed_company", session, {"into": "co", "identifier": "AAPL", "forms": ["10-Q"]}
    )
    assert outcome.error_code is None
    assert facade.calls[0] == ("company", "AAPL")
    assert facade.calls[1][0] == "company_filings"
    assert facade.calls[1][1]["forms"] == ("10-Q",)
    assert session.sets["co"].accessions == frozenset({_acc(8)})
    assert _run("seed_company", session, {"identifier": "  "}).error_code == "refused"
    assert _run("seed_company", session, {}).error_code == "refused"


def test_seed_dataset_json_shapes_and_parquet(tmp_path: Path) -> None:
    session = operator.ClientSession(facade=_FakeFacade())
    dicts = tmp_path / "rows.json"
    dicts.write_text(
        json.dumps([{"accession": _acc(1), "form": "10-K"}, {"accession": _acc(2)}]),
        encoding="utf-8",
    )
    outcome = _run("seed_dataset", session, {"into": "ds", "file": str(dicts)})
    assert outcome.error_code is None
    assert session.sets["ds"].accessions == frozenset({_acc(1), _acc(2)})
    assert session.sets["ds"].result is None
    strings = tmp_path / "list.json"
    strings.write_text(json.dumps({"accessions": [_acc(3)]}), encoding="utf-8")
    assert (
        _run("seed_dataset", session, {"into": "ds2", "file": str(strings)}).error_code
        is None
    )
    assert session.sets["ds2"].accessions == frozenset({_acc(3)})
    parquet = tmp_path / "rows.parquet"
    pq.write_table(pa.table({"accession": [_acc(4), _acc(5)]}), parquet)
    assert (
        _run("seed_dataset", session, {"into": "ds3", "file": str(parquet)}).error_code
        is None
    )
    assert session.sets["ds3"].accessions == frozenset({_acc(4), _acc(5)})
    assert session.current_set_name == "ds3"


def test_seed_dataset_refusals() -> None:
    session = operator.ClientSession(facade=_FakeFacade())
    assert _run("seed_dataset", session, {}).error_code == "refused"
    missing = _run("seed_dataset", session, {"file": "/no/such/dataset.json"})
    assert missing.error_code == "not_found"


def test_argv_host_refusals_and_success(tmp_path: Path, capsys) -> None:
    facade = _FakeFacade(fetch_result=_result(tmp_path, [(1, "10-K")]))
    session = operator.ClientSession(facade=facade)
    argv = ["--op", "seed_query", "--options", '{"limit": 5}', "--json"]
    assert operator.main(argv, session=session) == 1
    assert json.loads(capsys.readouterr().out)["error_code"] == "refused"
    argv = ["--op", "seed_snapshot", "--options", "{}", "--json"]
    assert operator.main(argv, session=session) == 1
    assert json.loads(capsys.readouterr().out)["error_code"] == "refused"
    argv = ["--op", "seed_query", "--options", '{"forms": ["10-K"]}', "--json"]
    assert operator.main(argv, session=session) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["error_code"] is None
    assert payload["data"]["count"] == 1


def test_combinator_algebra_identities(tmp_path: Path) -> None:
    session, _, _ = _session_with_sets(tmp_path)
    a = session.sets["a"].accessions
    b = session.sets["b"].accessions
    assert (
        _run("union", session, {"left": "a", "right": "b", "into": "u"}).error_code
        is None
    )
    assert session.sets["u"].accessions == a | b
    _run("union", session, {"left": "b", "right": "a", "into": "u2"})
    assert session.sets["u2"].accessions == a | b
    _run("intersect", session, {"left": "a", "right": "b", "into": "i"})
    assert session.sets["i"].accessions == a & b
    _run("difference", session, {"left": "a", "right": "b", "into": "d"})
    assert session.sets["d"].accessions == a - b
    assert not (session.sets["d"].accessions & b)
    _run("union", session, {"left": "d", "right": "i", "into": "rebuilt"})
    assert session.sets["rebuilt"].accessions == a
    assert session.current_set_name == "rebuilt"


def test_retention_rules(tmp_path: Path) -> None:
    session, res_a, _ = _session_with_sets(tmp_path)
    _run("difference", session, {"left": "a", "right": "b", "into": "d"})
    retained = session.sets["d"].result
    assert retained is not None
    assert retained.run_id == res_a.run_id
    assert (
        operator_selection.result_accessions(retained) == session.sets["d"].accessions
    )
    _run("intersect", session, {"left": "a", "right": "b", "into": "i"})
    assert session.sets["i"].result is not None
    assert (
        operator_selection.result_accessions(session.sets["i"].result)
        == session.sets["i"].accessions
    )
    _run("union", session, {"left": "a", "right": "b", "into": "u"})
    assert session.sets["u"].result is None
    _run("union", session, {"left": "a", "right": "i", "into": "u2"})
    assert session.sets["u2"].result is res_a
    peek = _run("peek", session, {"name": "u"})
    assert peek.error_code is None
    assert peek.total == len(session.sets["u"])


def test_query_backed_retention_wraps_query_sql(tmp_path: Path) -> None:
    result = FilingsResult(
        run_id="run-q",
        plan_id="plan-q",
        target_parquet_glob="",
        run_state_sqlite_path=tmp_path / "state.sqlite",
        artifacts_root=tmp_path,
        query_backed=True,
        query_sql="SELECT * FROM src",
        query_params=(),
    )
    filtered = operator_selection.filter_result_to_accessions(
        result, frozenset({_acc(2), _acc(1)})
    )
    assert "accession IN (?, ?)" in filtered.query_sql
    assert filtered.query_params == (_acc(1), _acc(2))
    emptied = operator_selection.filter_result_to_accessions(result, frozenset())
    assert "WHERE 1 = 0" in emptied.query_sql


def test_remove_keep_by_accession_partition_and_retention(tmp_path: Path) -> None:
    session, _, _ = _session_with_sets(tmp_path)
    a = session.sets["a"].accessions
    picked = sorted(a)[:2]
    _run(
        "remove_accessions",
        session,
        {"source": "a", "into": "removed", "accessions": picked},
    )
    _run(
        "keep_accessions",
        session,
        {"source": "a", "into": "kept", "accessions": picked},
    )
    assert session.sets["kept"].accessions == frozenset(picked)
    assert session.sets["removed"].accessions == a - frozenset(picked)
    assert not (session.sets["kept"].accessions & session.sets["removed"].accessions)
    assert operator_selection.result_accessions(
        session.sets["kept"].result
    ) == frozenset(picked)
    _run("remove_accessions", session, {"source": "a", "accessions": picked})
    assert session.sets["a"].accessions == a - frozenset(picked)
    bad = _run("keep_accessions", session, {"source": "a", "accessions": []})
    assert bad.error_code == "invalid_options"


def test_remove_keep_by_form_partition_and_refusal(tmp_path: Path) -> None:
    session, _, _ = _session_with_sets(tmp_path)
    a = session.sets["a"].accessions
    _run("keep_form", session, {"source": "a", "into": "k10", "forms": ["10-K"]})
    _run("remove_form", session, {"source": "a", "into": "no10k", "forms": ["10-k"]})
    assert session.sets["k10"].accessions == frozenset({_acc(1), _acc(3)})
    assert session.sets["no10k"].accessions == a - session.sets["k10"].accessions
    assert (
        operator_selection.result_accessions(session.sets["k10"].result)
        == session.sets["k10"].accessions
    )
    session.add_set("bare", [_acc(9)])
    assert (
        _run("keep_form", session, {"source": "bare", "forms": ["10-K"]}).error_code
        == "refused"
    )
    assert (
        _run("remove_form", session, {"source": "bare", "forms": ["10-K"]}).error_code
        == "refused"
    )
    assert (
        _run("keep_form", session, {"source": "a", "forms": []}).error_code
        == "invalid_options"
    )


def test_combinator_missing_sets_are_not_found(tmp_path: Path) -> None:
    session, _, _ = _session_with_sets(tmp_path)
    outcome = _run("union", session, {"left": "a", "right": "ghost", "into": "u"})
    assert outcome.error_code == "not_found"
    assert (
        _run("diff", session, {"left": "a", "right": "ghost"}).error_code == "not_found"
    )
    assert _run("drop_set", session, {"name": "ghost"}).error_code == "not_found"


def test_drop_and_clear(tmp_path: Path) -> None:
    session, _, _ = _session_with_sets(tmp_path)
    assert _run("drop_set", session, {"name": "a"}).error_code is None
    assert "a" not in session.sets
    assert session.current_set_name == "b"
    _run("drop_set", session, {})
    assert session.sets == {}
    assert session.current_set_name == ""
    session.add_set("x", [_acc(1)])
    outcome = _run("clear_sets", session, {})
    assert outcome.data == {"cleared": 1}
    assert session.sets == {}


def test_vars_peek_diff_payloads(tmp_path: Path) -> None:
    session, _, _ = _session_with_sets(tmp_path)
    vars_result = _run("vars", session, {})
    assert vars_result.error_code is None
    payload = json.loads(json.dumps(vars_result.to_payload()))
    assert payload["data"]["current_set"] == "b"
    assert payload["data"]["sets"] == [
        {"name": "a", "count": 4, "current": False},
        {"name": "b", "count": 4, "current": True},
    ]
    assert (vars_result.total, vars_result.shown) == (2, 2)
    peek = _run("peek", session, {"name": "a", "limit": 2})
    assert (peek.total, peek.shown) == (4, 2)
    assert peek.data["rows"][0] == {
        "accession": _acc(1),
        "form": "10-K",
        "filing_date": "2024-01-01",
    }
    session.add_set("bare", [_acc(9), _acc(7)])
    bare_peek = _run("peek", session, {"name": "bare"})
    assert bare_peek.data["rows"] == [{"accession": _acc(7)}, {"accession": _acc(9)}]
    assert _run("peek", session, {"name": "ghost"}).error_code == "not_found"
    diff = _run("diff", session, {"left": "a", "right": "b", "sample_limit": 1})
    assert diff.data["left_total"] == diff.data["right_total"] == 4
    assert diff.data["intersection"] == 2
    assert diff.data["left_only"] == diff.data["right_only"] == 2
    assert diff.data["left_only_sample"] == [_acc(1)]
    assert json.dumps(diff.to_payload())


def test_working_set_helper_for_step6_seeds(tmp_path: Path) -> None:
    result = _result(tmp_path, [(1, "10-K"), (2, "10-Q")])
    from_result = operator_selection.make_working_set(result=result)
    assert from_result.accessions == frozenset({_acc(1), _acc(2)})
    assert from_result.result is result
    bare = operator_selection.make_working_set([_acc(3)])
    assert bare.accessions == frozenset({_acc(3)})
    assert bare.result is None


def _fake_prompt(answers: dict[str, str]):
    def prompt(prompt: str, default: str = "") -> str:
        for key, value in answers.items():
            if prompt.startswith(key):
                return value
        return default

    return prompt


def test_gatherers_cover_selection_rows(monkeypatch) -> None:
    ids = {row[0] for row in operator_selection._SPEC_ROWS}
    assert set(operator_selection.GATHERERS) == ids
    assert ids <= set(operator.GATHERERS)
    monkeypatch.setattr(
        operator_selection,
        "prompt_text",
        _fake_prompt({"tickers": "AAPL", "forms": "10-K"}),
    )
    session = operator.ClientSession(facade=_FakeFacade())
    options = operator_selection.GATHERERS["seed_query"](session)
    assert isinstance(options, operator_selection.SeedQueryOptions)
    assert options.tickers == ("AAPL",)
    assert options.forms == ("10-K",)
    assert options.into == "main"


def test_menu_action_gathers_then_executes(tmp_path: Path, monkeypatch, capsys) -> None:
    facade = _FakeFacade(fetch_result=_result(tmp_path, [(1, "10-K")]))
    session = operator.ClientSession(facade=facade)
    monkeypatch.setattr(
        operator_selection, "prompt_text", _fake_prompt({"forms": "10-K"})
    )
    menu = operator.build_operator_menu(session)
    action = next(
        item
        for item in menu
        if isinstance(item, MenuAction) and item.label == "Seed from fetch query"
    )
    action.callback()
    assert session.current_set_name == "main"
    assert session.sets["main"].accessions == frozenset({_acc(1)})
    assert "Seeded set main" in capsys.readouterr().out
