"""Grouped interactive console for cohort tasks."""

from __future__ import annotations

import subprocess
import sys

from edgar_sec.foundation.runtime.interactive import (
    MenuAction,
    MenuSeparator,
    build_menu as make_menu,
    menu_action,
    prompt_choice,
    prompt_text,
    run_interactive_menu,
)


def _run_cli(*arguments: str) -> None:
    from edgar_sec.pipelines.cohort.cli import main

    main(list(arguments))


def _refresh_source() -> None:
    source = prompt_choice(
        "Official source to refresh",
        [("1", "Universe (cik_lookup)"), ("2", "Active tickers")],
    )
    source_name = "cik_lookup" if source == "1" else "company_tickers"
    from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
    from edgar_sec.infra.sec_http.client import SecHttpClient
    from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
    from edgar_sec.infra.storage.cohort.paths import resolve_cohort_paths
    from edgar_sec.infra.storage.cohort.sources import refresh_official_source

    settings = resolve_runtime_settings()
    paths = resolve_cohort_paths()
    client = SecHttpClient.from_settings(
        settings.sec, cache_dir=settings.cache_root, ttl_s=settings.ttl_s
    )
    record = refresh_official_source(
        source_name,
        client=client,
        paths=paths,
        catalog=CohortCatalog(paths),
    )
    print(f"active {source_name}: {record.cohort_id}")


def _assign_families() -> None:
    from edgar_sec.foundation.runtime.paths import resolve_paths

    paths = resolve_paths()
    result = subprocess.run(
        [
            sys.executable,
            str(paths.repo_root / "run.py"),
            "metadata",
            "family-index",
            "--artifacts",
            str(paths.artifacts_root),
        ],
        check=False,
    )
    if result.returncode:
        print(f"Family-index command exited with status {result.returncode}.")


def _source_menu() -> None:
    actions = make_menu(
        menu_action("Refresh official source", _refresh_source),
        menu_action("Assign company families", _assign_families),
        MenuSeparator(),
    )
    run_interactive_menu("Official Sources & Taxonomy", actions)


def _import() -> None:
    source = prompt_text("Input file")
    name = prompt_text("Cohort name (optional)")
    tags = prompt_text("Tags (comma-separated, optional)")
    arguments = ["import", "--input", source]
    if name:
        arguments.extend(("--name", name))
    if tags:
        arguments.extend(("--tags", tags))
    _run_cli(*arguments)


def _workspace_menu() -> None:
    actions = make_menu(
        menu_action("Initialize session", lambda: _prompt_workspace("init")),
        menu_action("Show current session", lambda: _run_cli("workspace", "current")),
        menu_action("List sessions", lambda: _run_cli("workspace", "sessions")),
        menu_action("Switch session", lambda: _prompt_workspace("use")),
        MenuSeparator("Variables"),
        menu_action("Bind cohort", lambda: _prompt_workspace("bind")),
        menu_action("Define expression", lambda: _prompt_workspace("let")),
        menu_action("Diff variables", lambda: _prompt_workspace("diff")),
        menu_action("List variables", lambda: _run_cli("workspace", "list")),
        menu_action("Peek variable", lambda: _prompt_workspace("peek")),
        menu_action("Save variable as cohort", lambda: _prompt_workspace("save")),
        menu_action("Drop variable", lambda: _prompt_workspace("drop")),
        menu_action("Clear session variables", lambda: _run_cli("workspace", "clear")),
    )
    run_interactive_menu("Cohort Workspace", actions)


def _prompt_workspace(command: str) -> None:
    if command in {"init", "use"}:
        _run_cli("workspace", command, prompt_text("Session id"))
    elif command == "bind":
        _run_cli("workspace", "bind", prompt_text("Alias"), prompt_text("Cohort"))
    elif command == "let":
        _run_cli(
            "workspace",
            "let",
            prompt_text("Variable"),
            prompt_text("Expression"),
        )
    elif command == "diff":
        _run_cli(
            "workspace",
            "diff",
            prompt_text("Left variable"),
            prompt_text("Right variable"),
        )
    elif command == "peek":
        _run_cli("workspace", "peek", prompt_text("Variable"))
    elif command == "save":
        _run_cli(
            "workspace",
            "save",
            prompt_text("Variable"),
            "--name",
            prompt_text("Cohort name"),
        )
    elif command == "drop":
        _run_cli("workspace", "drop", prompt_text("Variable"))


def _sample() -> None:
    source = prompt_text("Source cohort or source name")
    method = prompt_choice(
        "Sampling method", [("1", "Hash modulo"), ("2", "Seeded random")]
    )
    arguments = [
        "sample",
        "--source",
        source,
        "--method",
        "modulo" if method == "1" else "random",
    ]
    limit = prompt_text("Maximum rows (optional)")
    if limit:
        arguments.extend(("--limit", limit))
    rate = prompt_text("Rate percent (optional)")
    if rate:
        arguments.extend(("--rate", rate))
    name = prompt_text("Output name (optional)")
    if name:
        arguments.extend(("--name", name))
    if (
        prompt_choice(
            "Group by company family?", [("1", "No"), ("2", "Yes")], default="1"
        )
        == "2"
    ):
        arguments.append("--group-family")
        arguments.extend(("--family-index", prompt_text("Family-index Parquet path")))
    _run_cli(*arguments)


def _query() -> None:
    kind = prompt_choice("Search", [("1", "One cohort"), ("2", "All cohorts")])
    name = prompt_text("Entity name contains (optional)")
    cik = prompt_text("CIK (optional)")
    if kind == "1":
        arguments = ["query", prompt_text("Cohort")]
    else:
        arguments = ["find"]
    if name:
        arguments.extend(("--name", name))
    if cik:
        arguments.extend(("--cik", cik))
    _run_cli(*arguments)


def _inspect() -> None:
    _run_cli("info", prompt_text("Cohort"))


def _maintain() -> None:
    cohort = prompt_text("Cohort")
    operation = prompt_choice(
        "Maintenance",
        [("1", "Rename"), ("2", "Add tags"), ("3", "Remove tags")],
    )
    if operation == "1":
        _run_cli("rename", cohort, "--name", prompt_text("New name"))
    elif operation == "2":
        _run_cli("tag", cohort, "--add", prompt_text("Tags, comma-separated"))
    else:
        _run_cli("untag", cohort, "--tags", prompt_text("Tags, comma-separated"))


def _delete() -> None:
    cohort = prompt_text("Cohort to delete")
    confirmation = prompt_text(f"Type {cohort!r} to confirm")
    if confirmation == cohort:
        _run_cli("delete", cohort)


def build_menu() -> tuple[MenuAction | MenuSeparator, ...]:
    return make_menu(
        MenuSeparator("Official Sources & Taxonomy"),
        menu_action("Refresh & manage official sources", _source_menu),
        menu_action(
            "Assign company families for the universe",
            _assign_families,
        ),
        MenuSeparator("Cohort Ingest & Algebra"),
        menu_action("Process file to cohort", _import),
        menu_action("Cohort workspace", _workspace_menu),
        menu_action("Sample cohort", _sample),
        MenuSeparator("Cohort Maintenance & Query"),
        menu_action("Query CIKs or entity names", _query),
        menu_action("Inspect cohort details", _inspect),
        menu_action("Rename / Tag cohort", _maintain),
        menu_action("Delete cohort", _delete),
    )


def _header() -> str:
    from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
    from edgar_sec.infra.storage.cohort.paths import resolve_cohort_paths

    paths = resolve_cohort_paths()
    catalog = CohortCatalog(paths)
    count = 0
    offset = 0
    while True:
        page = catalog.list_cohorts(limit=500, offset=offset)
        count += len(page)
        if len(page) < 500:
            break
        offset += len(page)
    return f"Catalog: {paths.catalog_file} | Cohorts: {count} | Family Index: cohort pipeline"


def run_console() -> int:
    return run_interactive_menu(
        "Cohort Management Console (Layer 4)",
        build_menu(),
        before_menu=_header,
    )


__all__ = ["build_menu", "run_console"]
