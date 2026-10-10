from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from edgar_sec.pipelines.document_acquisition.commands.common import response_byte_limit
from edgar_sec.pipelines.document_acquisition.fixture_operator import (
    capture_fixture_case,
    create_fixture,
    list_fixture_cases,
    list_fixtures,
    replay_fixture_case,
)
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths


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
        root = create_fixture(args.fixture_id, paths=paths)
    except (OSError, RuntimeError, sqlite3.Error, ValueError) as error:
        return _fixture_error("create", args, error)
    payload = {
        "command": "fixture create",
        "fixture_id": args.fixture_id,
        "path": str(root),
        "status": "created",
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"created fixture {args.fixture_id}: {root}")
    return 0


def cmd_fixture_capture(args: argparse.Namespace) -> int:
    try:
        max_response_bytes = response_byte_limit(args.max_response_bytes)
        paths = resolve_acquisition_paths(artifacts_root=args.artifacts)
        result = capture_fixture_case(
            args.fixture_id,
            args.run_id,
            args.target_id,
            args.attempt_id,
            paths=paths,
            max_response_bytes=max_response_bytes,
        )
    except (
        KeyError,
        OSError,
        RuntimeError,
        sqlite3.Error,
        TypeError,
        ValueError,
    ) as error:
        return _fixture_error("capture", args, error)
    payload = {"command": "fixture capture", **asdict(result), "status": "captured"}
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        body = (
            f", response={result.response_sha256} ({result.source_byte_size} bytes)"
            if result.response_sha256 is not None
            else ", metadata only"
        )
        reused = ", reused response" if result.reused_response else ""
        print(
            f"captured {result.fixture_id}/{result.capture_id}/{result.target_id}: "
            f"{result.acquisition_status}{body}{reused}"
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
        fixtures = list_fixtures(paths)
        if args.fixture_id is not None:
            fixtures = (
                fixture_id for fixture_id in fixtures if fixture_id == args.fixture_id
            )
        cases = list_fixture_cases(
            paths,
            fixture_id=args.fixture_id,
            capture_id=args.capture_id,
            target_id=args.target_id,
        )
        if args.json:
            with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stream:
                stream.write('{"cases":')
                _write_json_array((asdict(case) for case in cases), stream=stream)
                stream.write(',"command":"fixture list","fixtures":')
                _write_json_array(fixtures, stream=stream)
                stream.write(',"status":"ok"}\n')
                stream.seek(0)
                shutil.copyfileobj(stream, sys.stdout)
        else:
            found_fixtures = False
            for fixture_id in fixtures:
                print(f"fixture {fixture_id}")
                found_fixtures = True
            found_cases = False
            for case in cases:
                print(
                    f"  {case.capture_id}/{case.target_id}: {case.acquisition_status}; "
                    f"attempt={case.attempt_id}; response={case.response_sha256 or 'none'}; "
                    f"selected={case.selected_sha256 or 'none'}"
                )
                found_cases = True
            if not found_fixtures:
                print("No fixtures found.")
            elif not found_cases:
                print("No fixture cases found.")
    except (OSError, RuntimeError, sqlite3.Error, ValueError) as error:
        return _fixture_error("list", args, error)
    return 0


def cmd_fixture_replay(args: argparse.Namespace) -> int:
    try:
        paths = resolve_acquisition_paths(artifacts_root=args.artifacts)
        result = replay_fixture_case(
            args.fixture_id,
            args.capture_id,
            args.target_id,
            Path(args.output),
            paths=paths,
        )
    except (OSError, RuntimeError, sqlite3.Error, ValueError) as error:
        return _fixture_error("replay", args, error)
    payload = {
        "command": "fixture replay",
        **asdict(result),
        "output_path": str(result.output_path) if result.output_path else None,
        "status": "replayed" if result.output_path else "metadata_only",
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    elif result.output_path is None:
        print(
            f"replayed {result.fixture_id}/{result.capture_id}/{result.target_id}: "
            f"{result.acquisition_status}; metadata only"
        )
    else:
        print(
            f"replayed {result.fixture_id}/{result.capture_id}/{result.target_id}: "
            f"{result.selected_byte_size} bytes to {result.output_path}"
        )
    return 0
