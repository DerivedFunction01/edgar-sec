from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import asdict

from tqdm.auto import tqdm

from edgar_sec.pipelines.document_acquisition.commands.common import response_byte_limit
from edgar_sec.pipelines.document_acquisition.fixture_store.capture import (
    capture_fixture_run,
    create_fixture,
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
    try:
        max_body_bytes = response_byte_limit(None)
        paths = resolve_acquisition_paths(artifacts_root=args.artifacts)
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

            result = capture_fixture_run(
                args.fixture,
                args.run_id,
                paths=paths,
                max_body_bytes=max_body_bytes,
                on_target=update_progress,
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
    payload = {"command": "fixture fill", **asdict(result), "status": "filled"}
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            f"filled {result.fixture_id} from run {result.run_id}: "
            f"{result.captured_cases} byte cases captured; "
            f"{result.skipped_targets} targets skipped"
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
                    f"  {case.capture_id}/{case.target_id}: attempt={case.attempt_id}; "
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
