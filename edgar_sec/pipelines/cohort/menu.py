"""Grouped interactive console for cohort tasks."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.foundation.runtime.interactive import (
    MenuAction,
    MenuSeparator,
    PickItem,
    build_menu as make_menu,
    menu_action,
    prompt_choice,
    prompt_paginated_choice,
    prompt_text,
    run_interactive_menu,
)


def _run_cli(*arguments: str) -> None:
    from edgar_sec.pipelines.cohort.cli import main

    main(list(arguments))


def _cohort_label(record: object) -> str:
    tags = ", ".join(record.tags) or "none"
    name = f"{record.name} ({record.cohort_id})" if record.name else record.cohort_id
    return (
        f"{name}  {record.distinct_cik_count:,} CIKs | "
        f"tags: {tags} | origin: {record.origin_kind}"
    )


def pick_cohort(catalog: object) -> str | None:
    cohort_items: list[PickItem] = []
    offset = 0
    while True:
        records = catalog.list_cohorts(limit=500, offset=offset)
        cohort_items.extend(
            PickItem(
                key=record.cohort_id,
                label=_cohort_label(record),
                value=record.cohort_id,
            )
            for record in records
        )
        if len(records) < 500:
            break
        offset += len(records)
    alias_items: list[PickItem] = []
    for source_name, alias, title in (
        ("cik_lookup", "universe", "Active SEC Universe"),
        ("company_tickers", "tickers", "Active Operating Filers"),
    ):
        cohort_id = catalog.get_active_source_pointer(source_name)
        record = catalog.get_cohort(cohort_id) if cohort_id else None
        if record is not None:
            alias_items.append(
                PickItem(
                    key=alias,
                    label=f"{alias}  {title} | {_cohort_label(record)}",
                    value=alias,
                ),
            )
    items = alias_items + cohort_items
    chosen = prompt_paginated_choice(items, prompt_label="Select cohort")
    return chosen.value if chosen is not None else None


def pick_workspace_variable(workspace: object) -> str | None:
    items = [
        PickItem(
            key=variable.name,
            label=f"{variable.name}  {variable.kind} | {variable.target_id}",
            value=variable.name,
        )
        for variable in workspace.list_variables()
    ]
    chosen = prompt_paginated_choice(items, prompt_label="Select workspace variable")
    return chosen.value if chosen is not None else None


def pick_workspace_session(store: object) -> str | None:
    active = store.get_active_session()
    items = [
        PickItem(
            key=session_id,
            label=f"{session_id}{' (active)' if session_id == active else ''}",
            value=session_id,
        )
        for session_id in store.list_sessions()
    ]
    chosen = prompt_paginated_choice(items, prompt_label="Select workspace session")
    return chosen.value if chosen is not None else None


def pick_upload_file(base_dir: str | Path = "uploads") -> str | None:
    directory = Path(base_dir)
    files = (
        sorted((path for path in directory.iterdir() if path.is_file()), key=str)
        if directory.is_dir()
        else []
    )
    items = [
        PickItem(key=path.name, label=str(path), value=str(path)) for path in files
    ]
    chosen = prompt_paginated_choice(items, prompt_label="Select upload file")
    return chosen.value if chosen is not None else None


def _workspace_context() -> tuple[object, object]:
    from edgar_sec.foundation.runtime.paths import resolve_paths
    from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
    from edgar_sec.infra.storage.cohort.paths import resolve_cohort_paths
    from edgar_sec.infra.storage.object_store.store import ObjectStore

    paths = resolve_cohort_paths(project_paths=resolve_paths())
    catalog = CohortCatalog(paths)
    store = ObjectStore(paths.catalog_file)
    store.initialize_schema()
    return catalog, store


def _workspace(catalog: object, store: object) -> object:
    from edgar_sec.foundation.runtime.paths import resolve_paths
    from edgar_sec.infra.storage.cohort.paths import resolve_cohort_paths
    from edgar_sec.infra.storage.cohort.workspace import CohortWorkspace

    paths = resolve_cohort_paths(project_paths=resolve_paths())
    return CohortWorkspace(paths, catalog=catalog, store=store)


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


def _publish_family_index() -> None:
    _run_cli("family-index")


def _source_menu() -> None:
    actions = make_menu(
        menu_action("Refresh official source", _refresh_source),
        menu_action("Assign company families", _assign_families),
        MenuSeparator(),
    )
    run_interactive_menu("Official Sources & Taxonomy", actions)


def _import() -> None:
    source = pick_upload_file()
    if source is None:
        return
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
    if command == "init":
        _run_cli("workspace", command, prompt_text("Session id"))
    elif command == "use":
        _catalog, store = _workspace_context()
        session_id = pick_workspace_session(store)
        if session_id is not None:
            _run_cli("workspace", command, session_id)
    elif command == "bind":
        catalog, store = _workspace_context()
        cohort = pick_cohort(catalog)
        if cohort is not None:
            _run_cli("workspace", "bind", prompt_text("Alias"), cohort)
    elif command == "let":
        _run_cli(
            "workspace",
            "let",
            prompt_text("Variable"),
            prompt_text("Expression"),
        )
    elif command == "diff":
        catalog, store = _workspace_context()
        workspace = _workspace(catalog, store)
        left = pick_workspace_variable(workspace)
        if left is None:
            return
        right = pick_workspace_variable(workspace)
        if right is not None:
            _run_cli("workspace", "diff", left, right)
    elif command == "peek":
        catalog, store = _workspace_context()
        variable = pick_workspace_variable(_workspace(catalog, store))
        if variable is not None:
            _run_cli("workspace", "peek", variable)
    elif command == "save":
        catalog, store = _workspace_context()
        variable = pick_workspace_variable(_workspace(catalog, store))
        if variable is not None:
            _run_cli(
                "workspace",
                "save",
                variable,
                "--name",
                prompt_text("Cohort name"),
            )
    elif command == "drop":
        catalog, store = _workspace_context()
        variable = pick_workspace_variable(_workspace(catalog, store))
        if variable is not None:
            _run_cli("workspace", "drop", variable)


def _sample() -> None:
    from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
    from edgar_sec.infra.storage.cohort.paths import resolve_cohort_paths

    source = pick_cohort(CohortCatalog(resolve_cohort_paths()))
    if source is None:
        return
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
        from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
        from edgar_sec.infra.storage.cohort.paths import resolve_cohort_paths

        cohort = pick_cohort(CohortCatalog(resolve_cohort_paths()))
        if cohort is None:
            return
        arguments = ["query", cohort]
    else:
        arguments = ["find"]
    if name:
        arguments.extend(("--name", name))
    if cik:
        arguments.extend(("--cik", cik))
    _run_cli(*arguments)


def _inspect() -> None:
    from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
    from edgar_sec.infra.storage.cohort.paths import resolve_cohort_paths

    cohort = pick_cohort(CohortCatalog(resolve_cohort_paths()))
    if cohort is not None:
        _run_cli("info", cohort)


def _maintain() -> None:
    from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
    from edgar_sec.infra.storage.cohort.paths import resolve_cohort_paths

    cohort = pick_cohort(CohortCatalog(resolve_cohort_paths()))
    if cohort is None:
        return
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
    from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
    from edgar_sec.infra.storage.cohort.paths import resolve_cohort_paths

    cohort = pick_cohort(CohortCatalog(resolve_cohort_paths()))
    if cohort is None:
        return
    confirmation = prompt_text(f"Type {cohort!r} to confirm")
    if confirmation == cohort:
        _run_cli("delete", cohort)


def build_menu() -> tuple[MenuAction | MenuSeparator, ...]:
    return make_menu(
        MenuSeparator("Official Sources & Taxonomy"),
        menu_action("Refresh & manage official sources", _source_menu),
        menu_action(
            "Publish family index for the universe",
            _publish_family_index,
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
