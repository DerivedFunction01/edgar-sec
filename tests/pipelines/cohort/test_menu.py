"""Grouped menu separators remain non-selectable and render as dividers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from edgar_sec.foundation.runtime import interactive
from edgar_sec.foundation.runtime.interactive import MenuAction, MenuSeparator
from edgar_sec.pipelines.cohort import menu


def test_grouped_menu_separators_do_not_consume_numeric_keys() -> None:
    actions = menu.build_menu()
    choices = [action for action in actions if isinstance(action, MenuAction)]
    separators = [action for action in actions if isinstance(action, MenuSeparator)]

    assert [action.key for action in choices] == [
        str(number) for number in range(1, 11)
    ]
    family_action = next(action for action in choices if "family index" in action.label)
    assert family_action.callback == menu._publish_family_index
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
    assert "10. Delete cohort" in output
    assert "0. Exit" in output


def test_workspace_menu_adds_repl_without_removing_session_workflows(
    monkeypatch,
) -> None:
    captured = {}
    monkeypatch.setattr(
        menu,
        "run_interactive_menu",
        lambda _title, actions: captured.setdefault("actions", actions),
    )
    calls = []
    monkeypatch.setattr(menu, "_run_cli", lambda *args: calls.append(args))

    menu._workspace_menu()

    choices = [
        action
        for action in captured["actions"]
        if isinstance(action, interactive.MenuAction)
    ]
    assert any(action.label == "Initialize session" for action in choices)
    assert any(action.label == "Switch session" for action in choices)
    next(
        action for action in choices if action.label == "Open interactive REPL"
    ).callback()
    assert calls == [("repl",)]


def test_pick_cohort_includes_catalog_details_and_active_aliases(monkeypatch) -> None:
    universe = SimpleNamespace(
        cohort_id="c-universe",
        name="SEC Universe",
        distinct_cik_count=987654,
        tags=("official",),
        origin_kind="official_source",
    )
    curated = SimpleNamespace(
        cohort_id="c-curated",
        name=None,
        distinct_cik_count=12,
        tags=(),
        origin_kind="import",
    )
    tickers = SimpleNamespace(
        cohort_id="c-tickers",
        name="Operating Filers",
        distinct_cik_count=10000,
        tags=("official", "tickers"),
        origin_kind="official_source",
    )

    class Catalog:
        def list_cohorts(self, *, limit, offset):
            return [universe, curated] if offset == 0 else []

        def get_active_source_pointer(self, source):
            return {"cik_lookup": "c-universe", "company_tickers": "c-tickers"}.get(
                source
            )

        def get_cohort(self, cohort_id):
            return {"c-universe": universe, "c-tickers": tickers}.get(cohort_id)

    captured = {}

    def choose(items, *, prompt_label):
        captured["items"] = items
        captured["prompt_label"] = prompt_label
        return items[0]

    monkeypatch.setattr(menu, "prompt_paginated_choice", choose)

    assert menu.pick_cohort(Catalog()) == "universe"
    assert captured["prompt_label"] == "Select cohort"
    assert [item.key for item in captured["items"]] == [
        "universe",
        "tickers",
        "c-universe",
        "c-curated",
    ]
    assert "987,654 CIKs" in captured["items"][0].label
    assert "official" in captured["items"][0].label
    assert "official_source" in captured["items"][0].label
    assert "10,000 CIKs" in captured["items"][1].label
    assert "tags: official, tickers" in captured["items"][1].label
    assert "12 CIKs" in captured["items"][3].label
    assert "tags: none" in captured["items"][3].label


def test_workspace_pickers_return_selected_variable_and_session(monkeypatch) -> None:
    variable = SimpleNamespace(name="active", kind="cohort", target_id="c-1234567")
    workspace = SimpleNamespace(list_variables=lambda: [variable])
    store = SimpleNamespace(
        get_active_session=lambda: "second",
        list_sessions=lambda: ["first", "second"],
    )
    prompts = []

    def choose(items, *, prompt_label):
        prompts.append((prompt_label, items))
        return items[-1]

    monkeypatch.setattr(menu, "prompt_paginated_choice", choose)

    assert menu.pick_workspace_variable(workspace) == "active"
    assert menu.pick_workspace_session(store) == "second"
    assert prompts[0][0] == "Select workspace variable"
    assert prompts[0][1][0].label == "active  cohort | c-1234567"
    assert prompts[1][0] == "Select workspace session"
    assert prompts[1][1][1].label == "second (active)"


def test_upload_picker_lists_files_in_stable_order(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "b.csv").write_text("b", encoding="utf-8")
    (tmp_path / "a.tsv").write_text("a", encoding="utf-8")
    (tmp_path / "C.PARQUET").write_text("c", encoding="utf-8")
    (tmp_path / "d.text").write_text("d", encoding="utf-8")
    (tmp_path / "notes.md").write_text("notes", encoding="utf-8")
    (tmp_path / ".private.csv").write_text("hidden", encoding="utf-8")
    (tmp_path / "folder").mkdir()
    (tmp_path / "folder.csv").mkdir()
    (tmp_path / "linked.csv").symlink_to(tmp_path / "b.csv")
    captured = {}

    def choose(items, *, prompt_label):
        captured["items"] = items
        captured["prompt_label"] = prompt_label
        return items[0]

    monkeypatch.setattr(menu, "prompt_paginated_choice", choose)

    assert menu.pick_upload_file(tmp_path) == str(tmp_path / "a.tsv")
    assert [item.key for item in captured["items"]] == [
        "a.tsv",
        "b.csv",
        "C.PARQUET",
        "d.text",
    ]
    assert captured["prompt_label"] == "Select upload file"


def test_empty_upload_picker_cancels(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(menu, "prompt_text", lambda *_args, **_kwargs: "")

    assert menu.pick_upload_file(tmp_path / "missing") is None


def test_empty_upload_picker_accepts_explicit_supported_file(
    monkeypatch, tmp_path: Path
) -> None:
    explicit = tmp_path / "external.CSV"
    explicit.write_text("cik", encoding="utf-8")
    monkeypatch.setattr(menu, "prompt_text", lambda *_args, **_kwargs: str(explicit))

    assert menu.pick_upload_file(tmp_path / "empty") == str(explicit)


def test_empty_upload_picker_rejects_unsupported_explicit_file(
    monkeypatch, tmp_path: Path
) -> None:
    explicit = tmp_path / "notes.md"
    explicit.write_text("notes", encoding="utf-8")
    monkeypatch.setattr(menu, "prompt_text", lambda *_args, **_kwargs: str(explicit))

    assert menu.pick_upload_file(tmp_path / "empty") is None


def test_source_menu_routes_family_action_to_publisher(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(
        menu,
        "run_interactive_menu",
        lambda _title, actions: captured.setdefault("actions", actions),
    )
    calls = []
    monkeypatch.setattr(menu, "_publish_family_index", lambda: calls.append("publish"))

    menu._source_menu()

    family = next(
        action for action in captured["actions"] if "families" in action.label
    )
    family.callback()
    assert calls == ["publish"]


def test_diff_menu_invokes_cli_with_one_optional_delta(monkeypatch) -> None:
    from edgar_sec.infra.storage.cohort import catalog as catalog_module
    from edgar_sec.infra.storage.cohort import paths as paths_module

    monkeypatch.setattr(catalog_module, "CohortCatalog", lambda _paths: object())
    monkeypatch.setattr(paths_module, "resolve_cohort_paths", lambda: object())
    choices = iter(("universe", "tech"))
    calls = []
    monkeypatch.setattr(menu, "pick_cohort", lambda _catalog: next(choices))
    monkeypatch.setattr(menu, "prompt_choice", lambda *_args, **_kwargs: "3")
    monkeypatch.setattr(menu, "prompt_text", lambda *_args, **_kwargs: "tickers_only")
    monkeypatch.setattr(menu, "_run_cli", lambda *args: calls.append(args))

    menu._diff_cohorts()

    assert calls == [("diff", "universe", "tech", "--save-right-delta", "tickers_only")]


def test_diff_menu_cancels_when_picker_is_cancelled(monkeypatch) -> None:
    from edgar_sec.infra.storage.cohort import catalog as catalog_module
    from edgar_sec.infra.storage.cohort import paths as paths_module

    monkeypatch.setattr(catalog_module, "CohortCatalog", lambda _paths: object())
    monkeypatch.setattr(paths_module, "resolve_cohort_paths", lambda: object())
    calls = []
    monkeypatch.setattr(menu, "pick_cohort", lambda _catalog: None)
    monkeypatch.setattr(menu, "_run_cli", lambda *args: calls.append(args))

    menu._diff_cohorts()

    assert calls == []


def test_header_uses_catalog_count_query(monkeypatch) -> None:
    from edgar_sec.infra.storage.cohort import catalog as catalog_module
    from edgar_sec.infra.storage.cohort import paths as paths_module

    paths = SimpleNamespace(catalog_file="cohorts.sqlite")

    class Catalog:
        def __init__(self, _paths):
            pass

        def cohort_count(self):
            return 17

        def get_active_source_pointer(self, source):
            return {"cik_lookup": "c-universe", "company_tickers": "c-tickers"}[source]

        def get_active_family_index(self, _universe_id):
            return SimpleNamespace(family_index_id="a" * 32)

    monkeypatch.setattr(catalog_module, "CohortCatalog", Catalog)
    monkeypatch.setattr(paths_module, "resolve_cohort_paths", lambda: paths)

    assert menu._header() == (
        "Catalog: cohorts.sqlite | Cohorts: 17 | Universe: c-universe | "
        "Tickers: c-tickers | Family Index: " + "a" * 32
    )


def test_family_index_menu_handler_invokes_the_cohort_command(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(menu, "_run_cli", lambda *args: calls.append(args))

    menu._publish_family_index()

    assert calls == [("family-index",)]
