"""Command surface for the table classification pipeline."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any

from .options import SurfaceOptions, build_parser, options_from_args
from .planner import PlanError, build_plan, read_plan
from .translator import family_targets, plan_request_for, planning_triples

__all__ = ["main"]


def _emit(payload: dict[str, Any], as_json: bool, line: str) -> None:
    print(json.dumps(payload, sort_keys=True) if as_json else line)


def _cmd_translate(args: Any) -> int:
    families = tuple(args.family) or None
    stratum = args.stratum or None
    try:
        triples = planning_triples(families=families, stratum=stratum)
        rows = family_targets(families=families, stratum=stratum)
    except ValueError as error:
        print(f"translate failed: {error}", file=sys.stderr)
        return 1
    payload = {
        "command": "translate",
        "triples": [triple.as_dict() for triple in triples],
        "families": [
            {
                "family": row.family,
                "triples": [triple.as_dict() for triple in row.triples],
            }
            for row in rows
        ],
    }
    line = " ".join(
        f"{triple.role}:{triple.type}:optional={str(triple.optional).lower()}"
        for triple in triples
    )
    _emit(payload, args.json, line or "no exhibit targets declared")
    return 0


def _cmd_plan(args: Any, options: SurfaceOptions) -> int:
    paths = options.classification_paths()
    try:
        request = plan_request_for(
            tuple(args.accession),
            source_snapshot_id=args.snapshot_id or None,
            stratum=args.stratum or None,
            families=tuple(args.family) or None,
            normalize_version=args.normalize_version or None,
            renderer_version=args.renderer_version or None,
            form=args.form or "",
            provenance_route=args.provenance_route,
        )
        result = build_plan(request, paths)
        plan = read_plan(paths, result.plan_id)
    except (ValueError, PlanError) as error:
        print(f"plan failed: {error}", file=sys.stderr)
        return 1
    payload = {
        "command": "plan",
        "plan_id": plan.plan_id,
        "path": str(result.root),
        "filings": len(plan.filings),
        "profile_application": len(plan.profile_application),
        "document_targets": len(plan.document_targets),
        "work_items": len(plan.work_items),
    }
    _emit(
        payload,
        args.json,
        f"plan {plan.plan_id}: filings={len(plan.filings)} "
        f"targets={len(plan.document_targets)} "
        f"work_items={len(plan.work_items)} path={result.root}",
    )
    return 0


def _find_plan(options: SurfaceOptions, plan_id: str) -> Path:
    candidate = options.resolved_plans_root() / plan_id
    if (candidate / "plan.json").is_file():
        return candidate
    raise ValueError(f"no plan document for {plan_id} under {candidate.parent}")


def _cmd_inspect(args: Any, options: SurfaceOptions) -> int:
    try:
        _find_plan(options, args.plan_id)
        plan = read_plan(options.classification_paths(), args.plan_id)
    except (ValueError, PlanError, OSError) as error:
        print(f"inspect failed: {error}", file=sys.stderr)
        return 1
    header = plan.provenance
    payload = {
        "command": "inspect",
        "plan_id": plan.plan_id,
        "plan_format_version": header["plan_format_version"],
        "source_snapshot_id": header["source_snapshot_id"],
        "registry_state": header["registry_state"],
        "filings": len(plan.filings),
        "profile_application": len(plan.profile_application),
        "document_targets": len(plan.document_targets),
        "work_items": len(plan.work_items),
    }
    _emit(
        payload,
        args.json,
        f"plan {plan.plan_id}: filings={len(plan.filings)} "
        f"targets={len(plan.document_targets)} "
        f"work_items={len(plan.work_items)} "
        f"snapshot={header['source_snapshot_id']}",
    )
    return 0


def _cmd_status(args: Any, options: SurfaceOptions) -> int:
    plans_root = options.resolved_plans_root()
    plan_ids: list[str] = []
    if plans_root.is_dir():
        plan_ids = sorted(
            entry.name
            for entry in plans_root.iterdir()
            if (entry / "plan.json").is_file()
        )
    store_root = options.resolved_store_root()
    payload = {
        "command": "status",
        "plans": plan_ids,
        "plans_root": str(plans_root),
        "store_root": str(store_root),
        "store_published": store_root.is_dir() and any(store_root.iterdir()),
    }
    _emit(
        payload,
        args.json,
        f"plans={len(plan_ids)} store_published={payload['store_published']} "
        f"plans_root={plans_root}",
    )
    return 0


def _cmd_run(args: Any, options: SurfaceOptions) -> int:
    from .runner import RunError, run_plan

    try:
        report = run_plan(options.classification_paths(), args.plan_id)
    except (PlanError, RunError) as error:
        print(f"run failed: {error}", file=sys.stderr)
        return 1
    payload = {
        "command": "run",
        "plan_id": report.plan_id,
        "work_items": report.work_items,
    }
    _emit(
        payload,
        args.json,
        f"run {report.plan_id}: work_items={report.work_items}",
    )
    return 0


def _delegate(kind: str, args: Any, options: SurfaceOptions) -> int:
    """Hand a command to its owning lane's module when it is present."""
    candidates = {
        "review": (
            ("commands.review", ("main", "cmd_review")),
            ("review_artifacts", ("main",)),
        ),
        "fixture": (
            ("commands.fixture", ("main", "cmd_fixture")),
            ("fixture_store", ("main",)),
        ),
    }[kind]
    package = __package__ or "edgar_sec.pipelines.table_classification"
    for module_name, attrs in candidates:
        try:
            module = importlib.import_module(f".{module_name}", package)
        except ImportError:
            continue
        for attr in attrs:
            func = getattr(module, attr, None)
            if callable(func):
                return int(func(args, options))
    print(
        f"{kind} is owned by a sibling Step 7 lane and is not present "
        "in this tree yet; the CLI seam is ready for it",
        file=sys.stderr,
    )
    return 2


def main(argv: list[str] | None = None) -> int:
    """Run one table_classification command."""
    args = build_parser().parse_args(argv)
    options = options_from_args(args)
    if args.command == "translate":
        return _cmd_translate(args)
    if args.command == "plan":
        return _cmd_plan(args, options)
    if args.command == "inspect":
        return _cmd_inspect(args, options)
    if args.command == "status":
        return _cmd_status(args, options)
    if args.command == "run":
        return _cmd_run(args, options)
    if args.command in {"review", "fixture"}:
        return _delegate(args.command, args, options)
    return 2


if __name__ == "__main__":
    sys.exit(main())
