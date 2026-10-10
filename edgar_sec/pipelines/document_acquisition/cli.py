"""Stable command surface for document acquisition tracks."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from edgar_sec.foundation.hashing import is_sha256_hex_digest
from edgar_sec.domain.sec_urls import parse_archive_url
from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
from edgar_sec.foundation.runtime.settings.validators import positive_int_type
from edgar_sec.infra.broker.daemon import managed_broker
from edgar_sec.infra.broker.sec_broker import SecBrokerClient
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.sec_http.streaming import (
    StreamFailure,
    StreamFailureCode,
    StreamResult,
    StreamedResponse,
)
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.models import (
    AcquisitionPolicy,
    AcquisitionStatusReport,
)
from edgar_sec.pipelines.document_acquisition.project import (
    AcquisitionProjectError,
    project_acquisition_run,
)
from edgar_sec.pipelines.document_acquisition.runner import execute_acquisition_run
from edgar_sec.pipelines.document_acquisition.run_state.store import inspect_run_state
from edgar_sec.pipelines.document_acquisition.run_validation import (
    load_validated_work_order,
)

__all__ = ["build_parser", "main", "report_not_implemented"]


class _LazySecTransport:
    def __init__(
        self,
        factory: Callable[[], SecHttpClient],
    ) -> None:
        self._factory = factory
        self._http_client: SecHttpClient | None = None
        self._socket_directory: tempfile.TemporaryDirectory[str] | None = None
        self._broker_context: AbstractContextManager[SecBrokerClient] | None = None
        self._broker: SecBrokerClient | None = None

    def _start_broker(self) -> SecBrokerClient:
        if self._broker is not None:
            return self._broker
        self._http_client = self._factory()
        try:
            self._socket_directory = tempfile.TemporaryDirectory(
                prefix="edgar-sec-broker-"
            )
            socket_path = Path(self._socket_directory.name) / "broker.sock"
            context = managed_broker(socket_path, http_client=self._http_client)
            broker = context.__enter__()
        except Exception:
            try:
                self._http_client.close()
            finally:
                self._http_client = None
                if self._socket_directory is not None:
                    self._socket_directory.cleanup()
                    self._socket_directory = None
            raise
        self._broker_context = context
        self._broker = broker
        return broker

    def stream_to_file(
        self,
        url: str,
        destination: str | Path,
        *,
        max_response_bytes: int,
        validate_redirect: Callable[[str], None],
    ) -> StreamResult:
        archive = parse_archive_url(url)
        if archive is None:
            return StreamFailure("unsafe_redirect", False, None, "invalid archive URL")
        try:
            result = self._start_broker().stream_to_file(
                url,
                max_response_bytes=max_response_bytes,
                accession_cik=archive.archive_cik,
                accession_number=archive.accession,
                staging_root=Path(destination).parent,
            )
        except (OSError, RuntimeError) as error:
            return StreamFailure("transport_error", True, None, str(error))
        if result.status != "ok":
            code = cast(StreamFailureCode, result.error_code or "transport_error")
            return StreamFailure(
                code,
                bool(result.retryable),
                result.status_code,
                result.error_code or "SEC broker stream failed",
            )
        source = result.path
        if (
            source is None
            or result.sha256 is None
            or result.final_url is None
            or result.status_code is None
            or result.requested_url != url
            or result.size < 1
            or result.size > max_response_bytes
            or not is_sha256_hex_digest(result.sha256)
            or source.is_symlink()
            or not source.is_file()
            or source.stat().st_size != result.size
            or not source.resolve().is_relative_to(Path(destination).parent.resolve())
        ):
            return StreamFailure(
                "transport_error",
                False,
                result.status_code,
                "invalid broker stream result",
            )
        validate_redirect(result.final_url)
        os.replace(source, destination)
        return StreamedResponse(
            status_code=result.status_code,
            requested_url=result.requested_url,
            final_url=result.final_url,
            sha256=result.sha256,
            byte_size=result.size,
            content_type=result.content_type,
            content_encoding=result.content_encoding,
            path=Path(destination),
        )

    def close(self) -> None:
        try:
            if self._broker is not None:
                self._broker.close()
        finally:
            try:
                if self._broker_context is not None:
                    self._broker_context.__exit__(None, None, None)
            finally:
                try:
                    if self._http_client is not None:
                        self._http_client.close()
                finally:
                    if self._socket_directory is not None:
                        self._socket_directory.cleanup()


_TRACKS = {
    "project": "S9 target-plan projection",
    "status": "S9 run-state inspection",
    "run": "S9 network acquisition",
    "process": "S10 body processing",
    "publish": "S11 Parquet/DAG publication",
    "fixture create": "S9 fixture initialization",
    "fixture capture": "S9 fixture capture",
    "fixture list": "S9 fixture discovery",
    "fixture replay": "S9 fixture replay",
    "review build": "S7 review artifact generation",
    "review compare": "S7 review comparison",
    "review list": "S7 review discovery",
    "snapshot status": "S11 snapshot availability",
    "snapshot audit": "S9/S10 evidence audit",
}


def report_not_implemented(command: str, *, json_output: bool = False) -> int:
    track = _TRACKS[command]
    message = "This command track is not implemented; no work was performed."
    status = "not_implemented"
    if command == "publish":
        message = (
            "S11 publication is gated on representative S9/S10 evidence and explicit "
            "approval; no work was performed."
        )
        status = "blocked_by_gate"
    elif command == "snapshot status":
        message = "No acquisition snapshot is published; S11 publication remains gated."
    elif command == "snapshot audit":
        message = (
            "No S9/S10 evidence audit is implemented; no snapshot was read or written."
        )
    result = {
        "command": command,
        "implemented": False,
        "message": message,
        "status": status,
        "track": track,
    }
    if json_output:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"not implemented: {track}; {message}", file=sys.stderr)
    return 2


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--artifacts", default=None, help="artifacts root override")
    parser.add_argument("--json", action="store_true", help="emit JSON to stdout")


def cmd_project(args: argparse.Namespace) -> int:
    paths = resolve_acquisition_paths(artifacts_root=args.artifacts)
    try:
        result = project_acquisition_run(args.plan_id, paths=paths)
    except (AcquisitionProjectError, OSError, ValueError) as error:
        payload = {
            "command": "project",
            "error": str(error),
            "status": "error",
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"project failed: {error}", file=sys.stderr)
        return 1
    payload = {
        "command": "project",
        "executable_count": result.executable_count,
        "reused": result.reused,
        "run_id": result.run_id,
        "skipped_count": result.skipped_count,
        "status": "ready",
        "target_plan_digest": result.manifest["target_plan_digest"],
        "target_plan_id": result.manifest["target_plan_id"],
        "work_order_sha256": result.work_order_sha256,
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            f"projected {result.run_id}: {result.executable_count} executable, "
            f"{result.skipped_count} skipped, reused={result.reused}"
        )
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    paths = resolve_acquisition_paths(artifacts_root=args.artifacts)

    def transport_factory() -> SecHttpClient:
        settings = resolve_runtime_settings()
        return SecHttpClient.from_settings(
            settings.sec,
            cache_dir=settings.cache_root,
            ttl_s=settings.ttl_s,
        )

    report = execute_acquisition_run(
        args.run_id,
        retry_failures=args.retry_failures,
        paths=paths,
        policy=AcquisitionPolicy(
            max_response_bytes=args.max_response_bytes,
            requested_workers=args.workers,
        ),
        transport=_LazySecTransport(transport_factory),
        clock=lambda: datetime.now(UTC),
        confirm_stale_lock=args.confirm_stale_lock,
    )
    payload = {
        "attempted_count": report.attempted_count,
        "cancelled": report.cancelled,
        "command": "run",
        "non_retryable_failure_count": report.non_retryable_failure_count,
        "retryable_failure_count": report.retryable_failure_count,
        "run_id": report.run_id,
        "state": report.state,
        "target_counts": dict(report.target_counts),
        "status": "cancelled" if report.cancelled else "complete",
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            f"run {report.run_id}: state={report.state}, "
            f"attempted={report.attempted_count}, "
            f"pending={report.target_counts.get('pending', 0)}, "
            f"retryable_failures={report.retryable_failure_count}, "
            f"terminal_failures={report.non_retryable_failure_count}"
        )
    if report.cancelled:
        return 130
    return (
        1 if report.state in {"needs_retry", "complete_with_errors", "invalid"} else 0
    )


def _run_ids(paths) -> tuple[str, ...]:
    root = paths.runs_root
    if root.is_symlink():
        raise ValueError("acquisition runs root is unsafe")
    if not root.exists():
        return ()
    if not root.is_dir():
        raise ValueError("acquisition runs root is not a directory")
    run_ids = []
    for candidate in root.iterdir():
        if candidate.is_symlink() or not candidate.is_dir():
            continue
        try:
            paths.run_dir(candidate.name)
        except ValueError:
            continue
        run_ids.append(candidate.name)
    return tuple(sorted(run_ids))


def _inspect_run(paths, run_id: str) -> AcquisitionStatusReport:
    try:
        load_validated_work_order(paths, run_id)
    except (OSError, sqlite3.Error, TypeError, ValueError, KeyError) as error:
        report = inspect_run_state(
            run_id,
            database_path=paths.run_state_path(run_id),
            lock_path=paths.run_lock_path(run_id),
        )
        if report.state == "invalid":
            return report
        return replace(report, state="invalid", invalid_reason=str(error))
    return inspect_run_state(
        run_id,
        database_path=paths.run_state_path(run_id),
        lock_path=paths.run_lock_path(run_id),
    )


def _status_mapping(report: AcquisitionStatusReport) -> dict[str, object]:
    active_lock = report.active_lock
    return {
        "active_lock": (
            {
                "host": active_lock.host,
                "pid": active_lock.pid,
                "started_at_utc": active_lock.started_at_utc,
            }
            if active_lock
            else None
        ),
        "invalid_reason": report.invalid_reason,
        "non_retryable_failure_count": report.non_retryable_failure_count,
        "retryable_failure_count": report.retryable_failure_count,
        "run_id": report.run_id,
        "state": report.state,
        "target_counts": dict(report.target_counts),
    }


def cmd_status(args: argparse.Namespace) -> int:
    paths = resolve_acquisition_paths(artifacts_root=args.artifacts)
    try:
        run_ids = (args.run_id,) if args.run_id else _run_ids(paths)
        reports = [_inspect_run(paths, run_id) for run_id in run_ids]
    except (OSError, ValueError) as error:
        payload = {"command": "status", "error": str(error), "status": "error"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"status failed: {error}", file=sys.stderr)
        return 1
    invalid = any(report.state == "invalid" for report in reports)
    payload = {
        "command": "status",
        "runs": [_status_mapping(report) for report in reports],
        "status": "invalid" if invalid else "ok",
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    elif not reports:
        print("No acquisition runs found.")
    else:
        for report in reports:
            counts = ", ".join(
                f"{name}={count}"
                for name, count in sorted(report.target_counts.items())
                if count
            )
            print(f"{report.run_id}: {report.state}; {counts or 'no targets'}")
            if report.invalid_reason:
                print(f"  invalid: {report.invalid_reason}")
    return 1 if invalid else 0


def cmd_review_build(args: argparse.Namespace) -> int:
    return report_not_implemented("review build", json_output=args.json)


def cmd_review_compare(args: argparse.Namespace) -> int:
    return report_not_implemented("review compare", json_output=args.json)


def cmd_review_list(args: argparse.Namespace) -> int:
    return report_not_implemented("review list", json_output=args.json)


def cmd_snapshot_status(args: argparse.Namespace) -> int:
    return report_not_implemented("snapshot status", json_output=args.json)


def cmd_snapshot_audit(args: argparse.Namespace) -> int:
    return report_not_implemented("snapshot audit", json_output=args.json)


_TODO_HANDLERS = {
    "review build": cmd_review_build,
    "review compare": cmd_review_compare,
    "review list": cmd_review_list,
    "status": cmd_status,
    "snapshot status": cmd_snapshot_status,
    "snapshot audit": cmd_snapshot_audit,
}


def _set_todo(parser: argparse.ArgumentParser, command: str) -> None:
    parser.set_defaults(
        acquisition_command=command,
        func=_TODO_HANDLERS.get(command, _cmd_todo),
    )


def _cmd_todo(args: argparse.Namespace) -> int:
    return report_not_implemented(args.acquisition_command, json_output=args.json)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="acquisition",
        description="Project and operate on S9 acquisition runs.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    project = commands.add_parser("project", help="project a published S6 target plan")
    project.add_argument("--plan-id", required=True, help="published target-plan id")
    _add_output_options(project)
    project.set_defaults(func=cmd_project)

    status = commands.add_parser("status", help="inspect resumable acquisition runs")
    status.add_argument("--run-id", help="run identifier (default: list runs)")
    _add_output_options(status)
    _set_todo(status, "status")

    run = commands.add_parser("run", help="acquire pending S9 target bodies")
    run.add_argument("--run-id", required=True, help="projected acquisition run id")
    run.add_argument("--retry-failures", action="store_true")
    run.add_argument(
        "--workers",
        type=positive_int_type,
        help="upper bound clamped to resource capacity; acquisition runs serially",
    )
    run.add_argument(
        "--max-response-bytes",
        type=positive_int_type,
        required=True,
        help="finite decoded-response byte ceiling for each SEC request",
    )
    run.add_argument("--confirm-stale-lock", action="store_true")
    _add_output_options(run)
    run.set_defaults(func=cmd_run)

    process = commands.add_parser("process", help="process acquired target bodies")
    process.add_argument("--run-id", required=True, help="acquisition run id")
    process.add_argument("--workers", type=positive_int_type)
    _add_output_options(process)
    _set_todo(process, "process")

    publish = commands.add_parser("publish", help="publish an approved S11 snapshot")
    publish.add_argument("--run-id", required=True, help="completed acquisition run id")
    publish.add_argument("--branch", default="main")
    publish.add_argument("--expected-branch-tip", default=None)
    _add_output_options(publish)
    _set_todo(publish, "publish")

    fixture = commands.add_parser("fixture", help="manage S9 response fixtures")
    fixture_commands = fixture.add_subparsers(dest="fixture_command", required=True)
    fixture_create = fixture_commands.add_parser("create", help="initialize a fixture")
    fixture_create.add_argument("--fixture-id", required=True)
    _add_output_options(fixture_create)
    _set_todo(fixture_create, "fixture create")
    fixture_capture = fixture_commands.add_parser(
        "capture", help="capture run responses"
    )
    fixture_capture.add_argument("--fixture-id", required=True)
    fixture_capture.add_argument("--run-id", required=True)
    _add_output_options(fixture_capture)
    _set_todo(fixture_capture, "fixture capture")
    fixture_list = fixture_commands.add_parser("list", help="list validated fixtures")
    _add_output_options(fixture_list)
    _set_todo(fixture_list, "fixture list")
    fixture_replay = fixture_commands.add_parser(
        "replay", help="replay captured responses"
    )
    fixture_replay.add_argument("--fixture-id", required=True)
    fixture_replay.add_argument("--target-id", required=True)
    _add_output_options(fixture_replay)
    _set_todo(fixture_replay, "fixture replay")

    review = commands.add_parser("review", help="build and compare review artifacts")
    review_commands = review.add_subparsers(dest="review_command", required=True)
    review_build = review_commands.add_parser("build", help="build review artifacts")
    review_build.add_argument("--run-id", required=True)
    _add_output_options(review_build)
    _set_todo(review_build, "review build")
    review_compare = review_commands.add_parser("compare", help="compare review runs")
    review_compare.add_argument("--left", required=True)
    review_compare.add_argument("--right", required=True)
    _add_output_options(review_compare)
    _set_todo(review_compare, "review compare")
    review_list = review_commands.add_parser("list", help="list review runs")
    _add_output_options(review_list)
    _set_todo(review_list, "review list")

    snapshot = commands.add_parser("snapshot", help="inspect S11 status and evidence")
    snapshot_commands = snapshot.add_subparsers(dest="snapshot_command", required=True)
    for action in ("status", "audit"):
        snapshot_action = snapshot_commands.add_parser(action)
        _add_output_options(snapshot_action)
        _set_todo(snapshot_action, f"snapshot {action}")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
