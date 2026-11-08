"""Tests for the client operator session, registry, and hosts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, is_dataclass

import pytest

from edgar_sec.apps.client import cli, operator
from edgar_sec.apps.client.operator_discovery import operation_listing
from edgar_sec.foundation.runtime.interactive import MenuAction
from edgar_sec.foundation.runtime.render import Grid, KeyValueRow, ProseRow


class _FakeFacade:
    """A facade stand-in; the skeleton must not call it."""

    def __init__(self) -> None:
        self.calls: list[str] = []


class _FakeResult:
    def __init__(self, accessions: list[str]) -> None:
        self.accessions = accessions


@dataclass(frozen=True)
class _ProbeOptions:
    limit: int = field(
        default=5,
        metadata={"help": "Selects the maximum rows shown. Refused below 1."},
    )


def _probe_executor(options, session):
    rows = (("a", "1"), ("b", "2"))[: options.limit]
    return operator.OpResult(
        kind="grid",
        title="Probe",
        components=(Grid(headers=("k", "v"), rows=rows),),
        data={"rows": [list(row) for row in rows]},
        total=2,
        shown=len(rows),
    )


def _probe_spec(**overrides):
    values = {
        "id": "probe",
        "label": "Probe operation",
        "options_type": _ProbeOptions,
        "effect": "reads_state",
        "requires": "current_filing",
        "result_kind": "grid",
        "hints": ("session_summary",),
        "executor": _probe_executor,
    }
    values.update(overrides)
    return operator.OperationSpec(**values)


def _session() -> operator.ClientSession:
    return operator.ClientSession(facade=_FakeFacade())


def test_registry_integrity() -> None:
    assert operator.REGISTRY
    ids = [spec.id for spec in operator.REGISTRY.values()]
    assert len(ids) == len(set(ids))
    for spec in operator.REGISTRY.values():
        assert is_dataclass(spec.options_type)
        assert callable(spec.executor)
        assert spec.effect in operator.EFFECTS
        assert spec.requires in operator.REQUIREMENTS
        assert spec.result_kind in operator.RESULT_KINDS


def test_closed_vocabularies_reject_outside_values() -> None:
    with pytest.raises(ValueError):
        _probe_spec(effect="writes_everywhere")
    with pytest.raises(ValueError):
        _probe_spec(requires="everything")
    with pytest.raises(ValueError):
        operator.OpResult(kind="grid", error_code="made_up_code")
    with pytest.raises(ValueError):
        operator.assemble_registry((_probe_spec(),), (_probe_spec(),))


def test_registry_walking_listing_and_json() -> None:
    listing = operation_listing(operator.REGISTRY)
    assert listing["total"] == listing["shown"] == len(operator.REGISTRY)
    entries = {entry["id"]: entry for entry in listing["operations"]}
    session = _session()
    for spec in operator.REGISTRY.values():
        entry = entries[spec.id]
        assert entry["label"] == spec.label
        assert entry["effect"] == spec.effect
        assert entry["requires"] == spec.requires
        assert entry["result_kind"] == spec.result_kind
        schema_names = [item["name"] for item in entry["options"]]
        assert schema_names == [
            item.name for item in spec.options_type.__dataclass_fields__.values()
        ]
        result = operator.execute_operation(spec, session, spec.options_type())
        assert result.kind == spec.result_kind
        assert result.error_code is None or result.error_code in operator.ERROR_CODES
        payload = json.loads(json.dumps(result.to_payload()))
        assert payload["total"] == result.total
        assert payload["shown"] == result.shown
        assert payload["data"] == result.data


def test_session_state_and_lazy_facade() -> None:
    facade = _FakeFacade()
    session = operator.ClientSession(facade=facade)
    assert session.facade is facade
    assert facade.calls == []
    fresh = operator.ClientSession()
    assert fresh._facade is None
    result = _FakeResult(["A1", "A2"])
    working = session.add_set("tech", ["A1", "A2", "A1"], result=result)
    assert working.accessions == frozenset({"A1", "A2"})
    assert working.result is result
    assert session.current_set is working
    assert session.satisfies("selection")
    assert not session.satisfies("current_filing")
    session.select_filing("A1", aggregate=result)
    assert session.satisfies("current_filing")
    assert session.last_run_record == ""


def test_execute_custom_spec_and_context_refusal() -> None:
    session = _session()
    spec = _probe_spec()
    refused = operator.execute_operation(spec, session, _ProbeOptions())
    assert refused.error_code == "missing_context"
    session.select_filing("A1")
    result = operator.execute_operation(spec, session, _ProbeOptions(limit=1))
    assert result.error_code is None
    assert (result.total, result.shown) == (2, 1)
    assert isinstance(result.components[0], Grid)


def test_decode_options_coerces_and_refuses() -> None:
    spec = _probe_spec()
    assert operator.decode_options(spec, {"limit": "3"}).limit == 3
    assert operator.decode_options(spec, None).limit == 5
    with pytest.raises(ValueError):
        operator.decode_options(spec, {"bogus": 1})
    result = operator.execute_by_id(
        "probe", _session(), {"limit": "x"}, registry={"probe": spec}
    )
    assert result.error_code == "invalid_options"
    unknown = operator.execute_by_id("nope", _session())
    assert unknown.error_code == "unknown_operation"
    assert json.dumps(unknown.to_payload())


def test_session_header_renders_four_facts() -> None:
    session = _session()
    session.read_context.mode = "snapshot"
    session.read_context.snapshot = "v1"
    session.add_set("tech", ["A1", "A2"])
    session.select_filing("A1")
    header = operator.render_session_header(session)
    assert "mode: snapshot" in header
    assert "snapshot: v1" in header
    assert "current set: tech (2)" in header
    assert "current filing: A1" in header


def _menu_labels(session, registry=None) -> list[str]:
    menu = operator.build_operator_menu(session, registry=registry)
    return [item.label for item in menu if isinstance(item, MenuAction)]


def test_menu_gates_rows_on_requirement() -> None:
    registry = operator.assemble_registry(operator.REGISTRY.values(), (_probe_spec(),))
    session = _session()
    labels = _menu_labels(session, registry)
    assert "Probe operation" not in labels
    assert "Session summary" in labels
    assert "List operations" in labels
    assert "Operation help" in labels
    session.select_filing("A1")
    assert "Probe operation" in _menu_labels(session, registry)


def test_session_summary_result_is_key_value() -> None:
    session = _session()
    session.add_set("tech", ["A1"])
    result = operator.execute_by_id("session_summary", session, {"include_sets": False})
    assert result.kind == "key_value"
    assert result.data["current_set"] == "tech"
    assert "sets" not in result.data
    assert all(isinstance(row, KeyValueRow) for row in result.components)
    assert result.total == result.shown == len(result.components)


def test_argv_list_operations_text_and_json(capsys) -> None:
    assert operator.main(["--list-operations"]) == 0
    out = capsys.readouterr().out
    assert "session_summary" in out
    assert "include_sets" in out
    assert operator.main(["--list-operations", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total"] == len(operator.REGISTRY)
    entry = payload["operations"][0]
    assert entry["id"] == "session_summary"
    assert entry["options"][0]["name"] == "include_sets"
    assert entry["options"][0]["default"] is True


def test_argv_op_executes_with_options_json(capsys) -> None:
    session = _session()
    session.add_set("tech", ["A1", "A2"])
    argv = ["--op", "session_summary", "--options", '{"include_sets": false}']
    assert operator.main(argv, session=session) == 0
    out = capsys.readouterr().out
    assert "Session summary" in out
    assert "tech" in out
    argv = ["--op", "session_summary", "--options", '{"include_sets": true}', "--json"]
    assert operator.main(argv, session=session) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["error_code"] is None
    assert payload["data"]["sets"] == {"tech": 2}
    assert payload["total"] == payload["shown"]


def test_argv_op_help_is_generated(capsys) -> None:
    assert operator.main(["--op", "session_summary", "--help"]) == 0
    out = capsys.readouterr().out
    assert "include_sets" in out
    assert "Selects whether named working sets are listed" in out
    assert "True" in out


def test_argv_unknown_op_and_bad_options(capsys) -> None:
    assert operator.main(["--op", "nope", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error_code"] == "unknown_operation"
    assert operator.main(["--op", "session_summary", "--options", "{bad"]) == 1
    assert "invalid_options" in capsys.readouterr().out
    argv = ["--op", "session_summary", "--options", '{"bogus": 1}', "--json"]
    assert operator.main(argv) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error_code"] == "invalid_options"


def test_argv_fetch_vocabulary_dispatches_to_step1_cli(monkeypatch, capsys) -> None:
    calls: list[list[str]] = []

    def fake_cli_main(argv: list[str]) -> int:
        calls.append(argv)
        print("step1 cli")
        return 0

    monkeypatch.setattr(cli, "main", fake_cli_main)
    assert operator.main(["--forms", "10-K", "--mode", "fast"]) == 0
    assert calls == [["--forms", "10-K", "--mode", "fast"]]
    assert "step1 cli" in capsys.readouterr().out


def test_main_wires_menu_host_with_header(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_entrypoint(title, menu, cli_main, argv, **kwargs):
        captured["title"] = title
        captured["header"] = kwargs["before_menu"]()
        captured["labels"] = [
            item.label for item in menu if isinstance(item, MenuAction)
        ]
        return 0

    monkeypatch.setattr(operator, "operator_entrypoint", fake_entrypoint)
    session = _session()
    session.add_set("tech", ["A1"])
    assert operator.main([], session=session) == 0
    assert captured["title"] == operator.MENU_TITLE
    assert "current set: tech (1)" in str(captured["header"])
    assert "Session summary" in list(captured["labels"])


def test_menu_action_executes_and_renders(capsys) -> None:
    session = _session()
    menu = operator.build_operator_menu(session)
    action = next(
        item
        for item in menu
        if isinstance(item, MenuAction) and item.label == "Session summary"
    )
    action.callback()
    out = capsys.readouterr().out
    assert "Session summary" in out
    assert "mode" in out


def test_prose_result_kind_serializes() -> None:
    result = operator.OpResult(
        kind="prose",
        title="Note",
        components=(ProseRow("hello"),),
        data={"text": "hello"},
        total=1,
        shown=1,
    )
    assert json.loads(json.dumps(result.to_payload()))["data"] == {"text": "hello"}
