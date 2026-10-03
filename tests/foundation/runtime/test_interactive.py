"""Terminal prompt and menu-loop contracts.

The loop is shared by every pipeline operator, so a defect here is not one
pipeline's bug. Three properties are important and are pinned directly: a
blank answer must not run an action, one failing action must not end the session,
and the per-render header hook must not be able to hide the menu.
"""

from __future__ import annotations

from edgar_sec.foundation.runtime.interactive import (
    MenuAction,
    operator_entrypoint,
    prompt_choice,
    prompt_text,
    run_interactive_menu,
)


def _answers(monkeypatch, replies: list[str]) -> None:
    """Feed a scripted sequence of answers to every prompt, in order.

    ``raising=False`` because ``input`` is a builtin: the module resolves it at
    call time and has no attribute of its own to shadow.
    """
    pending = iter(replies)
    monkeypatch.setattr(
        "edgar_sec.foundation.runtime.interactive.input",
        lambda _prompt="": next(pending),
        raising=False,
    )


def test_a_blank_answer_re_renders_instead_of_running_the_first_action(
    monkeypatch, capsys
) -> None:
    """Defaulting to action 1 made a stray Return start a mutating command."""
    ran: list[str] = []
    _answers(monkeypatch, ["", "0"])
    exit_code = run_interactive_menu(
        "Title",
        [MenuAction("1", "Mutate", lambda: ran.append("1"))],
    )
    assert exit_code == 0
    assert ran == []
    assert capsys.readouterr().out.count("Title") == 2


def test_an_invalid_choice_does_not_run_anything(monkeypatch) -> None:
    ran: list[str] = []
    _answers(monkeypatch, ["nope", "0"])
    run_interactive_menu("Title", [MenuAction("1", "Mutate", lambda: ran.append("1"))])
    assert ran == []


def test_a_failing_action_is_reported_and_the_menu_continues(
    monkeypatch, capsys
) -> None:
    """An unexpected exception must not end the operator's session.

    A handler that catches only a few exception types lets anything else
    propagate out of the loop, and the session state the operator had built is
    gone.
    """
    ran: list[str] = []
    _answers(monkeypatch, ["1", "2", "0"])
    run_interactive_menu(
        "Title",
        [
            MenuAction(
                "1", "Explode", lambda: (_ for _ in ()).throw(AttributeError("x"))
            ),
            MenuAction("2", "Work", lambda: ran.append("2")),
        ],
    )
    out = capsys.readouterr().out
    assert ran == ["2"]
    assert "AttributeError" in out
    assert "Explode" in out


def test_an_interrupt_reports_what_the_pipeline_says_survives(
    monkeypatch, capsys
) -> None:
    _answers(monkeypatch, ["1", "0"])
    run_interactive_menu(
        "Title",
        [MenuAction("1", "Long", lambda: (_ for _ in ()).throw(KeyboardInterrupt))],
        interrupted_message="chunks are preserved",
    )
    assert "chunks are preserved" in capsys.readouterr().out


def test_the_header_hook_runs_once_per_render(monkeypatch, capsys) -> None:
    """Per render, not per session: a stale header is worse than none."""
    calls: list[int] = []

    def before_menu() -> str:
        calls.append(1)
        return f"header {len(calls)}"

    _answers(monkeypatch, ["", "0"])
    run_interactive_menu("Title", [], before_menu=before_menu)
    out = capsys.readouterr().out
    assert len(calls) == 2
    assert "header 1" in out and "header 2" in out


def test_an_empty_header_prints_nothing_extra(monkeypatch, capsys) -> None:
    _answers(monkeypatch, ["0"])
    run_interactive_menu("Title", [], before_menu=lambda: None)
    assert capsys.readouterr().out.strip() == "Title\n  0. Exit"


def test_a_failing_header_still_draws_the_menu(monkeypatch, capsys) -> None:
    """Refusing to render the menu would strand the operator with no way back."""

    def before_menu() -> str:
        raise OSError("state unreadable")

    ran: list[str] = []
    _answers(monkeypatch, ["1", "0"])
    run_interactive_menu(
        "Title",
        [MenuAction("1", "Work", lambda: ran.append("1"))],
        before_menu=before_menu,
    )
    out = capsys.readouterr().out
    assert ran == ["1"]
    assert "Could not resolve session state" in out
    assert "Title" in out


def test_prompt_text_returns_the_default_on_a_blank_answer(monkeypatch) -> None:
    _answers(monkeypatch, [""])
    assert prompt_text("Anything", "fallback") == "fallback"


def test_prompt_text_returns_the_default_on_end_of_input(monkeypatch) -> None:
    def raise_eof(_prompt: str = "") -> str:
        raise EOFError

    monkeypatch.setattr(
        "edgar_sec.foundation.runtime.interactive.input", raise_eof, raising=False
    )
    assert prompt_text("Anything", "fallback") == "fallback"


def test_prompt_choice_keeps_asking_until_a_valid_key(monkeypatch, capsys) -> None:
    _answers(monkeypatch, ["zzz", "b"])
    assert prompt_choice("Pick", [("a", "Alpha"), ("b", "Beta")]) == "b"
    assert "Invalid option" in capsys.readouterr().out


def test_the_entrypoint_runs_the_header_only_for_the_interactive_path(
    monkeypatch,
) -> None:
    """With arguments there is no session, so no state may be resolved or printed."""
    dispatched: list[list[str]] = []
    monkeypatch.setattr(
        "edgar_sec.foundation.runtime.interactive.run_interactive_menu",
        lambda *_a, **_k: 0,
    )
    assert (
        operator_entrypoint("T", [], lambda argv: dispatched.append(argv) or 0, ["x"])
        == 0
    )
    assert dispatched == [["x"]]


def test_the_entrypoint_renders_the_menu_with_no_arguments(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_menu(
        title, actions, exit_key="0", *, interrupted_message=None, before_menu=None
    ):
        seen["before"] = before_menu
        return 0

    monkeypatch.setattr(
        "edgar_sec.foundation.runtime.interactive.run_interactive_menu", fake_menu
    )
    assert (
        operator_entrypoint("T", [], lambda argv: 0, [], before_menu=lambda: "h") == 0
    )
    assert seen["before"] is not None
