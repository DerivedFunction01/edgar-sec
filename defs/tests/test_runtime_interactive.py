from __future__ import annotations

from defs.runtime.interactive import InteractivePhase, run_interactive


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
