"""Unified CLI and subparser dispatch for distributed work execution."""

from __future__ import annotations

import argparse
from pathlib import Path

from edgar_sec.foundation.runtime.paths import distribution_root
from edgar_sec.foundation.runtime.render import (
    Grid,
    KeyValueRow,
    ProseRow,
    render_output,
)
from edgar_sec.foundation.runtime.settings.validators import positive_int_type

from .discovery import discover_bundles
from .guards import (
    assert_pipeline_affinity,
    read_bundle_manifest,
    write_bundle_manifest,
)
from .partition import build_assignment, divide_chunks
from .protocol import DistributionAdapter
from .receipt import (
    RECEIPT_FILE_NAME,
    read_receipt,
    verify_receipt_digests,
    write_receipt,
)


def _shell_arg(value: str) -> str:
    """Quote an argument if it contains shell-sensitive characters."""
    if value and all(c not in value for c in " \t\n\"'\\$`*?[]{}();&|<>#~!()"):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


def cmd_export(
    adapter: DistributionAdapter,
    plan_id: str,
    *,
    worker_count: int,
    destination: Path | None = None,
    artifacts_root: Path | None = None,
) -> int:
    """Export worker bundles partitioned round-robin across workers."""
    plan = adapter.resolve_plan(plan_id, artifacts_root)
    chunk_count = adapter.get_chunk_count(plan)
    dest = (
        destination.resolve()
        if destination is not None
        else adapter.default_destination(plan_id).resolve()
    )
    dest.mkdir(parents=True, exist_ok=True)

    division = divide_chunks(chunk_count, worker_count)
    exported_rows: list[tuple[str, str, str]] = []

    for worker_id, chunk_ids in division.items():
        if not chunk_ids:
            continue
        assignment = build_assignment(
            adapter.pipeline_name, plan_id, worker_id, chunk_ids
        )
        bundle_dir = dest / worker_id
        bundle_dir.mkdir(parents=True, exist_ok=True)
        write_bundle_manifest(bundle_dir, assignment)
        adapter.export_worker_bundle(plan, assignment, bundle_dir)
        exported_rows.append(
            (worker_id, str(len(chunk_ids)), str(bundle_dir.relative_to(dest)))
        )

    render_output(
        [
            KeyValueRow("pipeline", adapter.pipeline_name),
            KeyValueRow("plan_id", plan_id),
            KeyValueRow("total_chunks", str(chunk_count)),
            KeyValueRow("worker_bundles", str(len(exported_rows))),
            KeyValueRow("destination", str(dest)),
            Grid(headers=("Worker", "Chunks", "Path"), rows=tuple(exported_rows)),
        ],
        title=f"Worker Bundles Exported ({adapter.pipeline_name})",
    )
    return 0


def cmd_worker(
    adapter: DistributionAdapter,
    bundle_dir: Path,
    *,
    worker_id: str | None = None,
    workers: int | None = None,
) -> int:
    """Execute assigned work chunks from a bundle and emit a signed receipt."""
    bundle_path = bundle_dir.resolve()
    manifest = read_bundle_manifest(bundle_path)
    assert_pipeline_affinity(manifest, adapter.pipeline_name)

    effective_worker = worker_id or str(manifest.get("worker_id", "worker"))
    receipt = adapter.execute_worker(bundle_path, effective_worker, workers=workers)
    write_receipt(receipt, bundle_path / RECEIPT_FILE_NAME)

    render_output(
        [
            KeyValueRow("pipeline", adapter.pipeline_name),
            KeyValueRow("plan_id", receipt.plan_id),
            KeyValueRow("worker_id", receipt.worker_id),
            KeyValueRow("completed_chunks", str(len(receipt.completed_chunks))),
            KeyValueRow("row_count", str(receipt.row_count)),
        ],
        title=f"Worker Completed ({receipt.worker_id})",
    )
    return 0


def cmd_import(
    adapter: DistributionAdapter,
    plan_id: str,
    source_bundle: Path,
    *,
    artifacts_root: Path | None = None,
) -> int:
    """Verify receipt digests and adopt returned chunks into coordinator tree."""
    bundle_path = source_bundle.resolve()
    manifest = read_bundle_manifest(bundle_path)
    assert_pipeline_affinity(manifest, adapter.pipeline_name)

    receipt = read_receipt(bundle_path / RECEIPT_FILE_NAME)
    valid, err = verify_receipt_digests(receipt, bundle_path)
    if not valid:
        raise ValueError(f"receipt digest verification failed: {err}")

    plan = adapter.resolve_plan(plan_id, artifacts_root)
    report = adapter.adopt_worker_bundle(plan, bundle_path, receipt)

    render_output(
        [
            KeyValueRow("pipeline", adapter.pipeline_name),
            KeyValueRow("plan_id", report.plan_id),
            KeyValueRow("worker_id", report.worker_id),
            KeyValueRow("adopted_chunks", str(len(report.adopted_chunks))),
            KeyValueRow("ignored_chunks", str(len(report.ignored_chunks))),
        ],
        title=f"Worker Chunks Adopted ({report.worker_id})",
    )
    return 0


def cmd_list(adapter: DistributionAdapter, destination: Path | None = None) -> int:
    """List discovered worker bundles and their completion status."""
    root = (
        destination.resolve()
        if destination is not None
        else distribution_root().resolve()
    )
    bundles = discover_bundles(root, pipeline=adapter.pipeline_name)
    if not bundles:
        render_output(
            [ProseRow("no worker bundles discovered")],
            title=f"Discovered Bundles ({adapter.pipeline_name})",
        )
        return 0

    rows = tuple(
        (
            b.worker_id,
            b.plan_id[:10],
            b.state,
            str(b.chunk_count),
            str(b.bundle_dir),
        )
        for b in bundles
    )
    render_output(
        [
            Grid(headers=("Worker", "Plan", "State", "Chunks", "Path"), rows=rows),
            KeyValueRow("total_bundles", str(len(bundles))),
        ],
        title=f"Discovered Bundles ({adapter.pipeline_name})",
    )
    return 0


def cmd_commands(
    adapter: DistributionAdapter,
    plan_id: str,
    *,
    worker_count: int = 2,
    destination: Path | None = None,
    artifacts_root: Path | None = None,
) -> int:
    """Render the full distributed execution lifecycle as shell commands."""
    plan = adapter.resolve_plan(plan_id, artifacts_root)
    chunk_count = adapter.get_chunk_count(plan)
    dest = destination or adapter.default_destination(plan_id)
    division = divide_chunks(chunk_count, worker_count)
    assigned = [(w_id, dest / w_id) for w_id, c_ids in division.items() if c_ids]

    p_name = adapter.pipeline_name
    lines: list[ProseRow] = [
        ProseRow("Coordinator (run first):"),
        ProseRow(
            f"  python run.py {p_name} distrib export"
            f" --plan-id {_shell_arg(plan_id)}"
            f" --workers {worker_count}"
            f" --destination {_shell_arg(str(dest))}"
        ),
    ]

    for idx, (w_id, b_path) in enumerate(assigned, start=1):
        lines.extend(
            [
                ProseRow(f"\nMachine {idx} ({w_id}):"),
                ProseRow(
                    f"  python run.py {p_name} distrib worker"
                    f" --bundle {_shell_arg(str(b_path))}"
                ),
            ]
        )

    lines.append(ProseRow("\nCoordinator (run once bundles return):"))
    for _, b_path in assigned:
        lines.append(
            ProseRow(
                f"  python run.py {p_name} distrib import"
                f" --plan-id {_shell_arg(plan_id)}"
                f" --source {_shell_arg(str(b_path))}"
            )
        )

    render_output(lines, title="Distributed Execution Commands")
    return 0


def attach_distrib_subparser(
    subparsers: argparse._SubParsersAction,
    adapter_factory: callable,
    *,
    subcommand_name: str = "distrib",
    help_text: str = "Distributed worker bundle lifecycle",
) -> argparse.ArgumentParser:
    """Attach distribution subcommand tree to any pipeline argument parser."""
    dist_parser = subparsers.add_parser(subcommand_name, help=help_text)
    dist_parser.add_argument("--artifacts", help="artifacts root override")
    commands = dist_parser.add_subparsers(dest="distrib_command", required=True)

    exp = commands.add_parser("export", help="export worker bundles")
    exp.add_argument("--plan-id", required=True, help="plan identifier")
    exp.add_argument(
        "--workers",
        type=positive_int_type,
        required=True,
        help="number of worker bundles",
    )
    exp.add_argument(
        "--destination",
        type=Path,
        default=None,
        help="destination directory override",
    )

    wrk = commands.add_parser("worker", help="execute assigned worker bundle")
    wrk.add_argument(
        "--bundle", type=Path, required=True, help="worker bundle directory"
    )
    wrk.add_argument("--worker", default=None, help="worker identifier (if ambiguous)")
    wrk.add_argument(
        "--threads",
        type=positive_int_type,
        default=None,
        help="local execution threads",
    )

    imp = commands.add_parser(
        "import", help="adopt worker bundle chunks on coordinator"
    )
    imp.add_argument("--plan-id", required=True, help="plan identifier")
    imp.add_argument(
        "--source", type=Path, required=True, help="returned bundle directory"
    )

    lst = commands.add_parser("list", help="list discovered worker bundles")
    lst.add_argument(
        "--destination",
        type=Path,
        default=None,
        help="distribution directory to scan",
    )

    cmd = commands.add_parser("commands", help="render distributed shell commands")
    cmd.add_argument("--plan-id", required=True, help="plan identifier")
    cmd.add_argument(
        "--workers",
        type=positive_int_type,
        default=2,
        help="number of worker bundles",
    )
    cmd.add_argument(
        "--destination",
        type=Path,
        default=None,
        help="destination directory override",
    )

    dist_parser.set_defaults(
        func=lambda args: dispatch_distrib_subcommand(args, adapter_factory(args))
    )
    return dist_parser


def dispatch_distrib_subcommand(
    args: argparse.Namespace, adapter: DistributionAdapter
) -> int:
    """Dispatch parsed arguments to the appropriate distribution action."""
    cmd = getattr(args, "distrib_command", None)
    artifacts = (
        Path(args.artifacts).resolve() if getattr(args, "artifacts", None) else None
    )

    if cmd == "export":
        return cmd_export(
            adapter,
            args.plan_id,
            worker_count=args.workers,
            destination=args.destination,
            artifacts_root=artifacts,
        )
    if cmd == "worker":
        return cmd_worker(
            adapter,
            args.bundle,
            worker_id=args.worker,
            workers=args.threads,
        )
    if cmd == "import":
        return cmd_import(
            adapter,
            args.plan_id,
            args.source,
            artifacts_root=artifacts,
        )
    if cmd == "list":
        return cmd_list(adapter, destination=args.destination)
    if cmd == "commands":
        return cmd_commands(
            adapter,
            args.plan_id,
            worker_count=args.workers,
            destination=args.destination,
            artifacts_root=artifacts,
        )
    return 1
