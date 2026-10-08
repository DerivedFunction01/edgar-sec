"""Grouped menu separators remain non-selectable and render as dividers."""

from __future__ import annotations

from edgar_sec.foundation.runtime import interactive
from edgar_sec.foundation.runtime.interactive import MenuAction, MenuSeparator
from edgar_sec.pipelines.cohort import menu


def test_grouped_menu_separators_do_not_consume_numeric_keys() -> None:
    actions = menu.build_menu()
    choices = [action for action in actions if isinstance(action, MenuAction)]
    separators = [action for action in actions if isinstance(action, MenuSeparator)]

    assert [action.key for action in choices] == [
        str(number) for number in range(1, 10)
    ]
    assert [separator.title for separator in separators] == [
        "Official Sources & Taxonomy",
        "Cohort Ingest & Algebra",
        "Cohort Maintenance & Query",
    ]


def test_console_renders_group_titles_and_exit_key(monkeypatch, capsys) -> None:
    responses = iter(["0"])
    monkeypatch.setattr(
        interactive, "prompt_text", lambda *_args, **_kwargs: next(responses)
    )
    monkeypatch.setattr(menu, "_header", lambda: "Catalog: test | Cohorts: 0")

    assert menu.run_console() == 0
    output = capsys.readouterr().out
    assert "── Official Sources & Taxonomy" in output
    assert "── Cohort Ingest & Algebra" in output
    assert "9. Delete cohort" in output
    assert "0. Exit" in output
