from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import asdict

from tqdm.auto import tqdm

from edgar_sec.pipelines.document_acquisition.commands.common import (
    _LazySecTransport,
    response_byte_limit,
    sec_transport_factory,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.capture import (
    create_fixture,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.plan_capture import (
    capture_fixture_plan,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.reader import (
    list_fixture_cases,
    list_fixture_summaries,
)
from edgar_sec.pipelines.document_acquisition.paths import (
    read_published_plan,
    resolve_acquisition_paths,
    resolve_document_planning_paths,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.models import (
    FixturePlanPin,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.schema import (
    fixture_plan_pin,
)


def _fixture_error(command: str, args: argparse.Namespace, error: Exception) -> int:
    if args.json:
        print(
            json.dumps(
                {
                    "command": f"fixture {command}",
                    "error": str(error),
                    "status": "error",
                },
                sort_keys=True,
            )
        )
    else:
        print(f"fixture {command} failed: {error}", file=sys.stderr)
    return 1


def cmd_fixture_create(args: argparse.Namespace) -> int:
    try:
        paths = resolve_acquisition_paths(artifacts_root=args.artifacts)
        plan_paths = resolve_document_planning_paths(artifacts_root=args.artifacts)
        plan = read_published_plan(args.plan_id, plan_paths)
        pin = FixturePlanPin(
            target_plan_id=plan.plan_id,
            target_plan_digest=plan.manifest["plan_digest"],
            target_plan_schema_version=plan.manifest["target_schema_version"],
        )
        root = create_fixture(args.fixture, pin, paths=paths)
    except (OSError, RuntimeError, sqlite3.Error, ValueError) as error:
        return _fixture_error("create", args, error)
    payload = {
        "command": "fixture create",
        "fixture_id": args.fixture,
        "path": str(root),
        "status": "created",
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"created fixture {args.fixture}: {root}")
    return 0


def cmd_fixture_fill(args: argparse.Namespace) -> int:
    if not args.allow_network:
        return _fixture_error(
            "fill", args, ValueError("pass --allow-network to fetch fixture inputs")
        )
    transport = _LazySecTransport(sec_transport_factory)
    try:
        max_body_bytes = response_byte_limit(None)
        paths = resolve_acquisition_paths(artifacts_root=args.artifacts)
        pin = fixture_plan_pin(paths, args.fixture)
        if args.plan_id is not None and args.plan_id != pin.target_plan_id:
            raise ValueError("selected plan differs from fixture plan pin")
        with tqdm(
            total=None,
            desc=f"Fixture {args.fixture}",
            unit="target",
            dynamic_ncols=True,
            disable=args.no_progress,
        ) as progress:

            def update_progress(current: int, total: int) -> None:
                if progress.total is None:
                    progress.total = total
                progress.update(1)

            fill_kwargs = {}
            if getattr(args, "workers", None) is not None:
                fill_kwargs["workers"] = args.workers
            result = capture_fixture_plan(
                args.fixture,
                paths=paths,
                max_body_bytes=max_body_bytes,
                transport=transport,
                limit=args.limit,
                on_target=update_progress,
                **fill_kwargs,
            )
    except (
        KeyError,
        OSError,
        RuntimeError,
        sqlite3.Error,
        TypeError,
        ValueError,
    ) as error:
        return _fixture_error("fill", args, error)
    finally:
        transport.close()
    payload = {"command": "fixture fill", **asdict(result), "status": "filled"}
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            f"filled {result.fixture_id} from plan: "
            f"{result.captured_cases} byte cases captured; "
            f"{result.skipped_targets} targets skipped; "
            f"{result.failed_targets} targets failed; "
            f"lazy indexes fetched={result.fetched_lazy_indexes}, "
            f"reused={result.reused_lazy_indexes}; "
            f"failure codes={result.failure_counts}"
        )
    return 0


def _write_json_array(values, *, stream=None) -> None:
    encoder = json.JSONEncoder(sort_keys=True)
    output = stream or sys.stdout
    output.write("[")
    first = True
    for value in values:
        if not first:
            output.write(",")
        output.write(encoder.encode(value))
        first = False
    output.write("]")


def cmd_fixture_list(args: argparse.Namespace) -> int:
    try:
        paths = resolve_acquisition_paths(artifacts_root=args.artifacts)
        fixtures = list(list_fixture_summaries(paths))
        if args.fixture is not None:
            fixtures = [item for item in fixtures if item.fixture_id == args.fixture]
        cases = list_fixture_cases(
            paths,
            fixture_id=args.fixture,
        )
        if args.json:
            with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stream:
                stream.write('{"cases":')
                _write_json_array((asdict(case) for case in cases), stream=stream)
                stream.write(',"command":"fixture list","fixtures":')
                _write_json_array((asdict(item) for item in fixtures), stream=stream)
                stream.write(',"status":"ok"}\n')
                stream.seek(0)
                shutil.copyfileobj(stream, sys.stdout)
        else:
            found_fixtures = False
            for item in fixtures:
                print(
                    f"fixture {item.fixture_id}: plan={item.target_plan_id} "
                    f"digest={item.target_plan_digest} "
                    f"schema={item.target_plan_schema_version}; "
                    f"captures={item.capture_count}, cases={item.case_count}"
                )
                found_fixtures = True
            found_cases = False
            for case in cases:
                print(
                    f"  {case.capture_id}/{case.target_id}: "
                    f"source={case.selection_source}; "
                    f"body={case.body_sha256} ({case.byte_size} bytes)"
                )
                found_cases = True
            if not found_fixtures:
                print("No fixtures found.")
            elif not found_cases:
                print("No fixture cases found.")
    except (OSError, RuntimeError, sqlite3.Error, ValueError) as error:
        return _fixture_error("list", args, error)
    return 0
