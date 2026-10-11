"""Review artifact commands for document acquisition."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.pipelines.document_acquisition.paths import (
    AcquisitionPaths,
    resolve_acquisition_paths,
)
from edgar_sec.pipelines.document_acquisition.schemas import (
    RECEIPT_SCHEMA_VERSION,
    RUN_SCHEMA_VERSION,
    StagedBodyRef,
)
from edgar_sec.infra.storage.review.paths import (
    ReviewPaths,
)


def _staged_body_refs_for_run(
    paths: AcquisitionPaths, run_id: str
) -> list[StagedBodyRef]:
    """Load staged body refs from run manifest and state."""
    import sqlite3

    run_dir = paths.run_dir(run_id)
    state_path = run_dir / "state.sqlite"

    refs: list[StagedBodyRef] = []
    conn = sqlite3.connect(str(state_path))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT target_id, staged_path, sha256, byte_size "
            "FROM targets WHERE state = 'completed' AND staged_path IS NOT NULL"
        )
        for row in cur.fetchall():
            target_id, staged_path, sha256, byte_size = row
            source_resp_path = run_dir / "handoff" / "bodies" / target_id / "response"
            if source_resp_path.exists():
                source_sha = file_sha256(source_resp_path)
                source_size = source_resp_path.stat().st_size
            else:
                source_sha = sha256
                source_size = byte_size
            refs.append(
                StagedBodyRef(
                    run_id=run_id,
                    target_id=target_id,
                    path=staged_path,
                    sha256=sha256,
                    byte_size=byte_size,
                    selected_filename=None,
                    source_response_path=source_resp_path
                    if source_resp_path.exists()
                    else None,
                    source_response_sha256=source_sha,
                    source_response_byte_size=source_size,
                )
            )
    finally:
        conn.close()
    return refs


def cmd_review_build(args: argparse.Namespace) -> int:
    """Build review artifacts for acquired bodies."""
    paths = resolve_acquisition_paths(artifacts_root=args.artifacts)
    run_id = args.run_id
    run_dir = paths.run_dir(run_id)

    refs = _staged_body_refs_for_run(paths, run_id)
    review_id = run_id

    review_paths = paths.review_paths(review_id)

    results: list[dict] = []
    for ref in refs:
        target_dir = review_paths.target_dir(ref.target_id)
        target_dir.mkdir(parents=True, exist_ok=True)

        source_inert = target_dir / "source.inert.html"
        representation_txt = target_dir / "representation.txt"
        observations_json = target_dir / "observations.json"

        source_path = ref.source_response_path
        if source_path and source_path.exists():
            # Copy sanitized HTML (inert)
            shutil.copy(source_path, source_inert)

        # Write representation.txt (the staged body text)
        staged_path = ref.path
        if staged_path.exists():
            text = staged_path.read_text(encoding="utf-8")
            representation_txt.write_text(text, encoding="utf-8")

        # Write observations.json
        obs = {
            "run_id": run_id,
            "target_id": ref.target_id,
            "source_sha256": ref.source_response_sha256,
            "selected_sha256": ref.sha256,
            "built_at": datetime.now(UTC).isoformat(),
        }
        observations_json.write_text(
            json.dumps(obs, sort_keys=True, indent=2), encoding="utf-8"
        )

        results.append({"target_id": ref.target_id, "status": "complete"})

    payload = {
        "command": "review_build",
        "review_id": review_id,
        "run_id": run_id,
        "status": "complete",
        "target_count": len(results),
        "targets": results,
    }

    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"review build {review_id}: {len(results)} targets processed")
    return 0


def cmd_review_compare(args: argparse.Namespace) -> int:
    """Compare two review runs."""
    left_id = args.left
    right_id = args.right

    left_paths = paths.review_paths(left_id)
    right_paths = paths.review_paths(right_id)

    left_targets = set(t.name for t in left_paths.targets_root.iterdir() if t.is_dir())
    right_targets = set(
        t.name for t in right_paths.targets_root.iterdir() if t.is_dir()
    )

    payload = {
        "command": "review_compare",
        "left_id": left_id,
        "right_id": right_id,
        "common_targets": sorted(left_targets & right_targets),
        "left_only": sorted(left_targets - right_targets),
        "right_only": sorted(right_targets - left_targets),
    }

    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            f"compare {left_id} vs {right_id}: "
            f"common={len(payload['common_targets'])}, "
            f"left_only={len(payload['left_only'])}, "
            f"right_only={len(payload['right_only'])}"
        )
    return 0


def cmd_review_list(args: argparse.Namespace) -> int:
    """List review runs."""
    paths = resolve_acquisition_paths(artifacts_root=args.artifacts)
    runs_root = paths.review_runs_root
    runs_root.mkdir(parents=True, exist_ok=True)

    runs = [d.name for d in runs_root.iterdir() if d.is_dir()]
    runs.sort()

    payload = {
        "command": "review_list",
        "runs": runs,
        "count": len(runs),
    }

    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"review list: {len(runs)} runs")
        for r in runs:
            print(f"  {r}")
    return 0
