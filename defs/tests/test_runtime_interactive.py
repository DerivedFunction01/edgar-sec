from __future__ import annotations

from defs.runtime.interactive import (
    ExtraAction,
    InteractivePhase,
    run_interactive,
)


class _ScriptedInput:
    def __init__(self, answers):
        self._answers = iter(answers)

    def __call__(self, prompt=""):
        try:
            return next(self._answers)
        except StopIteration:
            raise EOFError


def _capture(monkeypatch, answers):
    scripted = _ScriptedInput(answers)
    monkeypatch.setattr("builtins.input", scripted)


def test_interactive_merge_actions_hidden_when_unset(monkeypatch, capsys):
    captured = {}

    def ensure_plan():
        return {"partitions": [{"partition_id": 1}, {"partition_id": 2}]}

    phase = InteractivePhase(
        ensure_plan=ensure_plan,
        preview=lambda: {"sample": []},
        status=dict,
        run_partition=lambda pid: captured.setdefault("run", pid),
        partition_command=lambda pid: f"cmd {pid}",
    )
    _capture(monkeypatch, ["0"])
    run_interactive(phase)
    out = capsys.readouterr().out
    assert "Merge" not in out


def test_interactive_merge_partition_prompts_and_calls_callback(monkeypatch, capsys):
    seen: list[int] = []

    def ensure_plan():
        return {"partitions": [{"partition_id": 1}, {"partition_id": 2}]}

    def merge_partition(pid):
        seen.append(pid)
        return {"partition_id": pid, "row_count": 3}

    phase = InteractivePhase(
        ensure_plan=ensure_plan,
        preview=lambda: {"sample": []},
        status=dict,
        run_partition=lambda pid: None,
        partition_command=lambda pid: f"cmd {pid}",
        merge_partition=merge_partition,
        merge_final=lambda: {"row_count": 6},
    )
    _capture(monkeypatch, ["5", "1,2", "0"])
    run_interactive(phase)
    assert seen == [1, 2]
    out = capsys.readouterr().out
    assert '"partition_id": 1' in out
    assert "Merge a partition" in out
    assert "Merge all partition artifacts" in out


def test_interactive_merge_partition_empty_input_selects_all(monkeypatch, capsys):
    seen: list[int] = []

    def ensure_plan():
        return {"partitions": [{"partition_id": 1}, {"partition_id": 2}]}

    phase = InteractivePhase(
        ensure_plan=ensure_plan,
        preview=lambda: {"sample": []},
        status=dict,
        run_partition=lambda pid: None,
        partition_command=lambda pid: f"cmd {pid}",
        merge_partition=seen.append,
        merge_final=dict,
    )
    _capture(monkeypatch, ["5", "", "0"])
    run_interactive(phase)
    assert seen == [1, 2]


def test_interactive_merge_final_invokes_callback(monkeypatch, capsys):
    called = {"final": 0}

    def ensure_plan():
        return {"partitions": [{"partition_id": 1}]}

    phase = InteractivePhase(
        ensure_plan=ensure_plan,
        preview=lambda: {"sample": []},
        status=dict,
        run_partition=lambda pid: None,
        partition_command=lambda pid: f"cmd {pid}",
        merge_partition=lambda pid: {"partition_id": pid},
        merge_final=lambda: called.__setitem__("final", 1) or {"row_count": 3},
    )
    _capture(monkeypatch, ["6", "0"])
    run_interactive(phase)
    assert called["final"] == 1


def _extra_phase(callback):
    return InteractivePhase(
        ensure_plan=lambda: {"partitions": [{"partition_id": 1}]},
        preview=lambda: {"sample": []},
        status=dict,
        run_partition=lambda pid: None,
        partition_command=lambda pid: f"cmd {pid}",
        extra_actions=(ExtraAction("s", "Refresh source", callback),),
    )


def test_extra_action_renders_and_dispatches_dict_result(monkeypatch, capsys):
    seen: list[str] = []

    def callback():
        seen.append("s")
        return {"ok": True, "snapshot_id": "abc"}

    _capture(monkeypatch, ["s", "0"])
    run_interactive(_extra_phase(callback))
    out = capsys.readouterr().out
    assert seen == ["s"]
    assert "Refresh source" in out
    assert '"ok": true' in out


def test_extra_action_prints_message_result(monkeypatch, capsys):
    _capture(monkeypatch, ["s", "0"])
    run_interactive(_extra_phase(lambda: "cancelled"))
    out = capsys.readouterr().out
    assert "cancelled" in out


def test_extra_action_error_is_reported_and_menu_continues(monkeypatch, capsys):
    def boom():
        raise ValueError("no snapshots found")

    _capture(monkeypatch, ["s", "0"])
    run_interactive(_extra_phase(boom))
    out = capsys.readouterr().out
    assert "error: no snapshots found" in out


def test_extra_action_none_result_prints_nothing(monkeypatch, capsys):
    _capture(monkeypatch, ["s", "0"])
    run_interactive(_extra_phase(lambda: None))
    out = capsys.readouterr().out
    assert "Refresh source" in out
    assert "None" not in out
