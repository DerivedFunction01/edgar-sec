"""User-facing cohort command handlers and catalog orchestration."""

from __future__ import annotations

import json
import re
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edgar_sec.foundation.runtime.paths import resolve_paths
from edgar_sec.foundation.runtime.render import Grid, KeyValueRow, render_output
from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.models import CohortRecord
from edgar_sec.infra.storage.cohort.paths import CohortPaths, resolve_cohort_paths
from edgar_sec.infra.storage.object_store.store import ObjectStore
from edgar_sec.pipelines.cohort.options import build_parser


@dataclass(frozen=True, slots=True)
class _Context:
    paths: CohortPaths
    catalog: CohortCatalog
    store: ObjectStore


def _context() -> _Context:
    paths = _paths()
    catalog = CohortCatalog(paths)
    store = ObjectStore(paths.catalog_file)
    store.initialize_schema()
    store.clean_expired_sessions()
    return _Context(paths, catalog, store)


def _paths() -> CohortPaths:
    return resolve_cohort_paths(project_paths=resolve_paths())


def _dataset(context: _Context, record: CohortRecord) -> Path:
    return context.paths.resolve_relative_path(record.dataset_path)


def _resolve(context: _Context, identifier: str) -> CohortRecord:
    return context.catalog.resolve_cohort_identifier(identifier)


def _cmd_import(args: Any, context: _Context) -> int:
    from edgar_sec.infra.storage.cohort.ingestion import ingest_file_to_cohort

    result = ingest_file_to_cohort(
        args.input,
        catalog=context.catalog,
        paths=context.paths,
        name=args.name,
        tags=args.tags,
        delimiter="\t" if args.delimiter in {"\t", r"\t"} else args.delimiter,
        limit=args.limit,
    )
    print(result.cohort.cohort_id)
    print(
        f"rows={result.cohort.row_count} usable={result.quality.usable_rows} "
        f"rejected={result.quality.rejected_rows} duplicates={result.quality.duplicate_rows}"
    )
    return 0


def _cmd_list(args: Any, context: _Context) -> int:
    records = context.catalog.list_cohorts(
        tag=args.tag,
        pinned_only=args.pinned_only,
        search=args.search,
        limit=args.limit,
        offset=args.offset,
    )
    render_output(
        [
            Grid(
                headers=("Cohort ID", "Name", "Rows", "Tags"),
                rows=tuple(
                    (
                        record.cohort_id,
                        record.name or "-",
                        str(record.row_count),
                        ",".join(record.tags),
                    )
                    for record in records
                ),
            )
        ],
        title="Cohorts",
    )
    return 0


def _cmd_info(args: Any, context: _Context) -> int:
    from edgar_sec.infra.storage.cohort.query import query_cohort_members

    record = _resolve(context, args.cohort)
    print(f"id: {record.cohort_id}")
    print(f"name: {record.name or ''}")
    print(f"rows: {record.row_count}")
    print(f"distinct CIKs: {record.distinct_cik_count}")
    print(f"schema: {record.manifest_schema_ver}")
    print(f"dataset: {record.dataset_path}")
    print(f"dataset SHA-256: {record.dataset_sha256}")
    print(
        f"origin: {record.origin_kind} "
        f"{json.dumps(json.loads(record.origin_json), sort_keys=True)}"
    )
    print(f"tags: {', '.join(record.tags)}")
    _, members = query_cohort_members(_dataset(context, record), limit=5)
    print("sample:")
    for member in members:
        print(f"  {member.cik_padded}\t{member.name}")
    return 0


def _cmd_rename(args: Any, context: _Context) -> int:
    record = _resolve(context, args.cohort)
    context.catalog.rename_cohort(record.cohort_id, args.name)
    print(f"renamed {record.cohort_id} to {args.name}")
    return 0


def _cmd_tag(args: Any, context: _Context) -> int:
    if not args.add and not args.remove:
        raise ValueError("tag requires --add or --remove")
    record = _resolve(context, args.cohort)
    if args.add:
        context.catalog.add_tags(record.cohort_id, args.add)
    if args.remove:
        context.catalog.remove_tags(record.cohort_id, args.remove)
    print(f"updated tags for {record.cohort_id}")
    return 0


def _cmd_untag(args: Any, context: _Context) -> int:
    record = _resolve(context, args.cohort)
    context.catalog.remove_tags(record.cohort_id, args.remove)
    print(f"removed tags from {record.cohort_id}")
    return 0


def _cmd_delete(args: Any, context: _Context) -> int:
    record = _resolve(context, args.cohort)
    deleted = context.catalog.delete_cohort(
        record.cohort_id, purge_dataset=not args.keep_dataset
    )
    if not deleted:
        raise ValueError(f"Cohort not found: {args.cohort!r}")
    print(f"deleted {record.cohort_id}")
    return 0


def _cmd_query(args: Any, context: _Context) -> int:
    from edgar_sec.infra.storage.cohort.query import query_cohort_members

    record = _resolve(context, args.cohort)
    count, members = query_cohort_members(
        _dataset(context, record),
        cik=args.cik,
        name_substr=args.name,
        limit=args.limit,
        offset=args.offset,
    )
    print(f"matches={count} offset={args.offset}")
    render_output(
        [
            Grid(
                headers=("CIK", "Name"),
                rows=tuple((member.cik_padded, member.name) for member in members),
            )
        ],
        title="Cohort Members",
    )
    return 0


def _cmd_find(args: Any, context: _Context) -> int:
    from edgar_sec.infra.storage.cohort.query import find_across_cohorts

    if args.cik is None and args.name is None:
        raise ValueError("find requires --cik or --name")
    offset = (args.page - 1) * args.limit
    count, matches = find_across_cohorts(
        context.catalog,
        cik=args.cik,
        name_substr=args.name,
        limit=args.limit,
        offset=offset,
    )
    print(f"matches={count} page={args.page}")
    render_output(
        [
            Grid(
                headers=("Cohort ID", "Cohort Name", "CIK", "Name"),
                rows=tuple(
                    (
                        match.cohort_id,
                        match.cohort_name or "",
                        match.cik_padded,
                        match.name,
                    )
                    for match in matches
                ),
            )
        ],
        title="Cohort Matches",
    )
    return 0


def _source_record(context: _Context, source: str) -> CohortRecord:
    return _resolve(context, source)


def _cmd_sample(args: Any, context: _Context) -> int:
    from edgar_sec.infra.storage.cohort.operations import (
        FamilyIndexNotFoundError,
        sample_cohort,
    )
    from edgar_sec.infra.storage.cohort.ingestion import publish_derived_cohort

    if args.rate is None and args.limit is None:
        raise ValueError("sample requires --rate or --limit")
    if args.exclude_spv and not args.group_family:
        raise ValueError("--exclude-spv requires --group-family")
    if args.family_index and not args.group_family:
        raise ValueError("--family-index requires --group-family")
    if args.group_family and args.family_index is None:
        raise FamilyIndexNotFoundError("family index is missing; pass --family-index")
    record = _source_record(context, args.source)
    with tempfile.TemporaryDirectory(prefix="edgar-cohort-sample-") as temp_dir:
        output = Path(temp_dir) / "sample.parquet"
        row_count = sample_cohort(
            _dataset(context, record),
            output,
            method=args.method,
            rate_percent=args.rate,
            sample_limit=args.limit,
            seed=args.seed,
            family_index_dataset=args.family_index,
            group_by_family=args.group_family,
            exclude_spv=args.exclude_spv,
        )
        result = publish_derived_cohort(
            output,
            catalog=context.catalog,
            paths=context.paths,
            origin_kind="sample",
            origin_details={
                "source_cohort_id": record.cohort_id,
                "sampling_method": args.method,
                "rate_percent": args.rate,
                "sample_limit": args.limit,
                "seed": args.seed,
                "group_by_family": args.group_family,
                "family_index": args.family_index,
                "exclude_spv": args.exclude_spv,
            },
            name=args.name,
            tags=("sample",),
        )
    print(f"{result.cohort.cohort_id} rows={row_count}")
    return 0


def _cmd_family_index(_args: Any, context: _Context) -> int:
    from edgar_sec.pipelines.cohort.family_index import publish_family_index

    artifact, stats = publish_family_index(catalog=context.catalog, paths=context.paths)
    render_output(
        [
            KeyValueRow("family_index_id", artifact.record.family_index_id),
            KeyValueRow("dataset_path", str(artifact.dataset_path)),
            KeyValueRow("registrants", str(stats.registrants)),
            KeyValueRow("entity_families", str(stats.entity_families)),
            KeyValueRow("spv_families", str(stats.spv_families)),
            KeyValueRow("singletons", str(stats.singletons)),
            KeyValueRow("spv_registrants", str(stats.spv_registrants)),
            KeyValueRow("unresolved_sponsors", str(stats.unresolved_sponsors)),
        ],
        title="Family Index Published",
    )
    return 0


def _cmd_sources_refresh(args: Any, context: _Context, client: Any = None) -> int:
    from edgar_sec.infra.storage.cohort.sources import refresh_official_source

    if client is None:
        from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
        from edgar_sec.infra.sec_http.client import SecHttpClient

        settings = resolve_runtime_settings()
        client = SecHttpClient.from_settings(
            settings.sec, cache_dir=settings.cache_root, ttl_s=settings.ttl_s
        )
    record = refresh_official_source(
        args.source,
        client=client,
        paths=context.paths,
        catalog=context.catalog,
    )
    print(f"active {args.source}: {record.cohort_id}")
    return 0


def _cmd_diff(args: Any, context: _Context) -> int:
    from edgar_sec.infra.storage.cohort.ingestion import publish_derived_cohort
    from edgar_sec.infra.storage.cohort.operations import (
        diff_cohorts,
        execute_set_operation,
    )

    left = _source_record(context, args.left)
    right = _source_record(context, args.right)
    left_dataset = _dataset(context, left)
    right_dataset = _dataset(context, right)
    report = diff_cohorts(
        left_dataset,
        right_dataset,
        left_name=args.left,
        right_name=args.right,
    )
    render_output(
        [
            KeyValueRow("left", f"{args.left} ({report.left_total:,} CIKs)"),
            KeyValueRow("right", f"{args.right} ({report.right_total:,} CIKs)"),
            KeyValueRow("intersection", str(report.intersection_count)),
            KeyValueRow("left only", str(report.left_only_count)),
            KeyValueRow("right only", str(report.right_only_count)),
            KeyValueRow("union", str(report.union_count)),
            Grid(
                headers=("Delta", "CIK", "Name"),
                rows=tuple(
                    ("left only", cik, name) for cik, name in report.sample_left_only
                )
                + tuple(
                    ("right only", cik, name) for cik, name in report.sample_right_only
                ),
            ),
        ],
        title="Cohort Diff",
    )

    for side, name, source, base, origin_key in (
        ("left", args.save_left_delta, left, right, "left_only"),
        ("right", args.save_right_delta, right, left, "right_only"),
    ):
        if not name:
            continue
        with tempfile.TemporaryDirectory(prefix="edgar-cohort-diff-") as temp_dir:
            output = Path(temp_dir) / "delta.parquet"
            execute_set_operation(
                _dataset(context, source),
                _dataset(context, base),
                "difference",
                output,
            )
            result = publish_derived_cohort(
                output,
                catalog=context.catalog,
                paths=context.paths,
                origin_kind="set_operation",
                origin_details={
                    "operation": origin_key,
                    "source_cohort_id": source.cohort_id,
                    "base_cohort_id": base.cohort_id,
                },
                name=name,
                tags=("diff", f"diff:{side}"),
            )
        print(f"saved {side} delta: {result.cohort.cohort_id}")
    return 0


def _duration_seconds(value: str) -> int:
    match = re.fullmatch(r"([0-9]+)([smhd])", value.strip().lower())
    if match is None:
        raise ValueError(
            "duration must use seconds, minutes, hours, or days (e.g. 24h)"
        )
    amount = int(match.group(1))
    factor = {"s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2)]
    return amount * factor


def _cmd_doctor(paths: CohortPaths) -> int:
    from edgar_sec.infra.storage.cohort.maintenance import audit_cohort_store

    report = audit_cohort_store(paths)
    if report.healthy:
        print("cohort catalog healthy")
        return 0
    for finding in report.findings:
        print(f"issue: {finding}")
    return 1


def _cmd_maintain(args: Any, paths: CohortPaths) -> int:
    from edgar_sec.infra.storage.cohort.maintenance import maintain_cohort_store

    report = maintain_cohort_store(
        paths,
        clean_stale_staging=args.clean_stale_staging,
        clean_orphans=args.clean_orphans,
        clean_missing=args.clean_missing,
        clean_detached=args.clean_detached,
        clean_raw_snapshots=args.clean_raw_snapshots,
        all=args.all,
        force=args.force,
    )
    for name, count in report.removed:
        print(f"removed_{name}={count}")
    for warning in report.warnings:
        print(f"warning: {warning}")
    return 0


def _cmd_workspace(args: Any, context: _Context) -> int:
    command = args.workspace_command
    if command == "init":
        context.store.touch_session(args.session_id)
        context.store.set_active_session(args.session_id)
        print(args.session_id)
        return 0
    if command == "use":
        context.store.set_active_session(args.session_id)
        print(args.session_id)
        return 0
    if command == "current":
        session_id = context.store.get_active_session()
        aliases = context.store.list_aliases(session_id)
        print(f"{session_id} variables={len(aliases)}")
        return 0
    if command == "sessions":
        for session_id in context.store.list_sessions():
            print(session_id)
        return 0
    if command == "clean":
        removed = context.store.clean_expired_sessions(
            max_age_seconds=_duration_seconds(args.older_than)
        )
        print(f"removed_sessions={removed}")
        return 0

    from edgar_sec.infra.storage.cohort.workspace import CohortWorkspace

    session_id = args.session or context.store.get_active_session()
    workspace = CohortWorkspace(
        context.paths,
        catalog=context.catalog,
        store=context.store,
        session_id=session_id,
    )
    if command == "bind":
        workspace.bind_alias(args.alias, args.cohort)
        print(f"{args.alias} -> {args.cohort}")
    elif command == "let":
        print(workspace.let_expression(args.variable, args.expression))
    elif command == "diff":
        report = workspace.diff(args.left, args.right)
        print(f"{report.left_name}: {report.left_total}")
        print(f"{report.right_name}: {report.right_total}")
        print(f"intersection: {report.intersection_count}")
        print(f"left only: {report.left_only_count}")
        print(f"right only: {report.right_only_count}")
        print(f"union: {report.union_count}")
    elif command == "peek":
        for member in workspace.peek(args.variable, limit=args.limit):
            print(f"{member.cik_padded}\t{member.name}")
    elif command == "save":
        record = workspace.save(args.variable, args.name, tags=args.tags)
        print(record.cohort_id)
    elif command == "list":
        for variable in workspace.list_variables():
            print(f"{variable.name}\t{variable.target_id}\t{variable.kind}")
    elif command == "drop":
        print("dropped" if workspace.drop_var(args.variable) else "not found")
    elif command == "clear":
        workspace.clear()
        print(f"cleared {session_id}")
    else:
        raise ValueError(f"unsupported workspace command: {command!r}")
    return 0


def _cmd_merge(args: Any, context: _Context) -> int:
    from edgar_sec.foundation.serialization import canonical_json
    from edgar_sec.infra.storage.cohort.operations import (
        parse_expression,
        serialize_expression,
    )

    if not args.serialize and not args.name:
        raise ValueError("merge requires --name unless --serialize is used")
    node = parse_expression(args.expr)
    if args.serialize:
        print(canonical_json(serialize_expression(node)))
        return 0

    from edgar_sec.infra.storage.cohort.workspace import CohortWorkspace

    workspace = CohortWorkspace(
        context.paths,
        catalog=context.catalog,
        store=context.store,
    )
    variable = f"_cli_merge_{uuid.uuid4().hex}"
    try:
        workspace.let_expression(variable, args.expr)
        result = workspace.save(variable, args.name, tags=args.tags)
    finally:
        workspace.drop_var(variable)
    print(result.cohort.cohort_id)
    return 0


def _cmd_repl(_args: Any, context: _Context) -> int:
    from edgar_sec.pipelines.cohort.repl import run_repl

    return run_repl(context.paths, context.catalog, context.store)


def _dispatch(args: Any, context: _Context) -> int:
    handlers = {
        "import": _cmd_import,
        "list": _cmd_list,
        "info": _cmd_info,
        "rename": _cmd_rename,
        "tag": _cmd_tag,
        "untag": _cmd_untag,
        "delete": _cmd_delete,
        "query": _cmd_query,
        "find": _cmd_find,
        "sample": _cmd_sample,
        "diff": _cmd_diff,
        "family-index": _cmd_family_index,
        "workspace": _cmd_workspace,
        "repl": _cmd_repl,
        "merge": _cmd_merge,
    }
    if args.command == "sources":
        if args.sources_command == "refresh":
            return _cmd_sources_refresh(args, context)
        raise ValueError(f"unsupported sources command: {args.sources_command!r}")
    if args.command == "console":
        from edgar_sec.pipelines.cohort.menu import run_console

        return run_console()
    handler = handlers.get(args.command)
    if handler is None:
        raise ValueError(f"unsupported command: {args.command!r}")
    return handler(args, context)


def main(argv: list[str] | None = None, *, source_client: Any = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    if not arguments:
        arguments = ["console"]
    args = parser.parse_args(arguments)
    try:
        if args.command == "doctor":
            return _cmd_doctor(_paths())
        if args.command == "maintain":
            return _cmd_maintain(args, _paths())
        if args.command == "sources" and args.sources_command == "refresh":
            return _cmd_sources_refresh(args, _context(), client=source_client)
        return _dispatch(args, _context())
    except Exception as exc:  # noqa: BLE001 - command errors are reported with nonzero status
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
