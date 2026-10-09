"""Line-oriented interactive cohort workspace."""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable
from uuid import uuid4

from edgar_sec.foundation.runtime.render import Grid, render_output
from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.paths import CohortPaths
from edgar_sec.pipelines.cohort.workspace import CohortWorkspace
from edgar_sec.infra.storage.object_store.store import ObjectStore

_ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")
_COMMAND_ALIASES = {
    "b": "bind",
    "d": "diff",
    "ls": "vars",
    "p": "peek",
    "q": "exit",
    "rm": "drop",
    "s": "save",
    "?": "help",
}
_COMMANDS = {
    "bind",
    "clear",
    "diff",
    "drop",
    "exit",
    "help",
    "let",
    "list",
    "peek",
    "quit",
    "save",
    "use",
    "vars",
}


def _transient_session_id(store: ObjectStore) -> str:
    sessions = set(store.list_sessions())
    while True:
        session_id = f"repl_{uuid4().hex}"
        if session_id not in sessions:
            return session_id


def _assignment(line: str) -> tuple[str, str] | None:
    value = line.strip()
    explicit = value.startswith("let ")
    if explicit:
        value = value[4:].lstrip()
    match = _ASSIGNMENT.fullmatch(value)
    if match is None:
        if explicit:
            raise ValueError("use: let <variable> = <expression>")
        return None
    variable, expression = match.groups()
    if not expression.strip():
        raise ValueError("expression must not be empty")
    if variable.lower() in _COMMANDS or variable.lower() in _COMMAND_ALIASES:
        raise ValueError(f"reserved command name: {variable!r}")
    return variable, expression.strip()


def _render_diff(workspace: CohortWorkspace, left: str, right: str) -> None:
    report = workspace.diff(left, right)
    render_output(
        [
            Grid(
                headers=("Set", "Members"),
                rows=(
                    (report.left_name, str(report.left_total)),
                    (report.right_name, str(report.right_total)),
                    ("Intersection", str(report.intersection_count)),
                    ("Left only", str(report.left_only_count)),
                    ("Right only", str(report.right_only_count)),
                    ("Union", str(report.union_count)),
                ),
            )
        ],
        title="Cohort Diff",
    )


def _render_variables(workspace: CohortWorkspace) -> None:
    variables = workspace.list_variables()
    render_output(
        [
            Grid(
                headers=("Variable", "Kind", "Target ID"),
                rows=tuple(
                    (item.name, item.kind, item.target_id) for item in variables
                ),
            )
        ],
        title="Workspace Variables",
    )


def _execute(
    line: str,
    workspace: CohortWorkspace,
    *,
    paths: CohortPaths,
    catalog: CohortCatalog,
    store: ObjectStore,
    output: Callable[[str], None],
) -> tuple[bool, CohortWorkspace]:
    assignment = _assignment(line)
    if assignment is not None:
        variable, expression = assignment
        target_id = workspace.let_expression(variable, expression)
        output(f"{variable} -> {target_id}")
        return False, workspace

    try:
        tokens = shlex.split(line)
    except ValueError as exc:
        raise ValueError(f"invalid command quoting: {exc}") from exc
    if not tokens:
        return False, workspace
    command = _COMMAND_ALIASES.get(tokens[0].lower(), tokens[0].lower())
    arguments = tokens[1:]

    if command in {"exit", "quit"}:
        if arguments:
            raise ValueError("exit takes no arguments")
        return True, workspace
    if command == "help":
        output(
            "bind <alias> [cohort] | let <var> = <expr> | diff <left> <right> | "
            "peek <var> [limit] | vars | save <var> <name> [--tags a,b] | "
            "drop <var> | clear | use <session> | exit"
        )
    elif command == "bind":
        if len(arguments) not in {1, 2}:
            raise ValueError("use: bind <alias> [cohort]")
        cohort = arguments[1] if len(arguments) == 2 else None
        if cohort is None:
            from edgar_sec.pipelines.cohort.menu import pick_cohort

            cohort = pick_cohort(catalog)
            if cohort is None:
                return False, workspace
        workspace.bind_alias(arguments[0], cohort)
        output(f"{arguments[0]} -> {cohort}")
    elif command == "let":
        raise ValueError("use: let <variable> = <expression>")
    elif command == "diff":
        if len(arguments) != 2:
            raise ValueError("use: diff <left> <right>")
        _render_diff(workspace, *arguments)
    elif command == "peek":
        if len(arguments) not in {1, 2}:
            raise ValueError("use: peek <variable> [limit]")
        limit = int(arguments[1]) if len(arguments) == 2 else 10
        rows = workspace.peek(arguments[0], limit=limit)
        render_output(
            [
                Grid(
                    headers=("Ordinal", "CIK", "Name"),
                    rows=tuple(
                        (str(row.ordinal), row.cik_padded, row.name) for row in rows
                    ),
                )
            ],
            title=f"Preview: {arguments[0]}",
        )
    elif command in {"vars", "list"}:
        if arguments:
            raise ValueError(f"{command} takes no arguments")
        _render_variables(workspace)
    elif command == "save":
        if len(arguments) not in {2, 4} or (
            len(arguments) == 4 and arguments[2] != "--tags"
        ):
            raise ValueError("use: save <variable> <name> [--tags a,b]")
        tags = ()
        if len(arguments) == 4:
            tags = tuple(tag.strip() for tag in arguments[3].split(",") if tag.strip())
            if not tags:
                raise ValueError("provide at least one tag")
        record = workspace.save(arguments[0], arguments[1], tags=tags)
        output(f"saved {record.cohort_id}")
    elif command == "drop":
        if len(arguments) != 1:
            raise ValueError("use: drop <variable>")
        output("dropped" if workspace.drop_var(arguments[0]) else "not found")
    elif command == "clear":
        if arguments:
            raise ValueError("clear takes no arguments")
        for variable in workspace.list_variables():
            workspace.drop_var(variable.name)
        output(f"cleared {workspace.session_id}")
    elif command == "use":
        if len(arguments) != 1:
            raise ValueError("use: use <session>")
        session_id = arguments[0]
        if session_id not in store.list_sessions():
            raise ValueError(f"workspace session not found: {session_id!r}")
        workspace = CohortWorkspace(
            paths, catalog=catalog, store=store, session_id=session_id
        )
        output(f"using {session_id}")
    else:
        raise ValueError(f"unknown command: {tokens[0]!r}")
    return False, workspace


def run_repl(
    paths: CohortPaths,
    catalog: CohortCatalog,
    store: ObjectStore,
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> int:
    transient_session = _transient_session_id(store)
    workspace = CohortWorkspace(
        paths, catalog=catalog, store=store, session_id=transient_session
    )
    output_fn(
        f"Cohort workspace {transient_session} (transient); type help for commands"
    )
    try:
        while True:
            try:
                line = input_fn("cohort> ")
                should_exit, workspace = _execute(
                    line,
                    workspace,
                    paths=paths,
                    catalog=catalog,
                    store=store,
                    output=output_fn,
                )
            except (EOFError, KeyboardInterrupt):
                output_fn("")
                break
            except Exception as exc:
                output_fn(f"Error: {exc}")
                continue
            if should_exit:
                break
    finally:
        store.clear_session(transient_session)
        output_fn(f"closed transient session {transient_session}")
    return 0


__all__ = ["run_repl"]
