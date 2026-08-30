"""Golden comparison and divergence evidence helpers."""

from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def compare_golden(
    actual: str,
    expected_path: Path,
    report_root: Path,
    fixture_id: str,
    metadata: dict,
    *,
    update: bool = False,
) -> bool:
    """Compare or explicitly update one golden and persist divergence evidence."""
    if update:
        expected_path.write_text(actual, encoding="utf-8")
        return True
    expected = expected_path.read_text(encoding="utf-8")
    if actual == expected:
        return True
    output_dir = report_root / fixture_id
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "expected.txt").write_text(expected, encoding="utf-8")
    (output_dir / "actual.txt").write_text(actual, encoding="utf-8")
    diff = difflib.unified_diff(
        expected.splitlines(keepends=True),
        actual.splitlines(keepends=True),
        fromfile="expected",
        tofile="actual",
    )
    (output_dir / "diff.patch").write_text("".join(diff), encoding="utf-8")
    (output_dir / "metadata.json").write_text(
        json.dumps(
            {
                **metadata,
                "fixture_id": fixture_id,
                "expected_sha256": sha256_text(expected),
                "actual_sha256": sha256_text(actual),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return False


def compare_golden_value(
    actual: str,
    expected: str,
    report_root: Path,
    fixture_id: str,
    metadata: dict,
) -> bool:
    """Compare an expected value stored inside a tabular corpus artifact."""
    if actual == expected:
        return True
    output_dir = report_root / fixture_id
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "expected.txt").write_text(expected, encoding="utf-8")
    (output_dir / "actual.txt").write_text(actual, encoding="utf-8")
    diff = difflib.unified_diff(
        expected.splitlines(keepends=True),
        actual.splitlines(keepends=True),
        fromfile="expected",
        tofile="actual",
    )
    (output_dir / "diff.patch").write_text("".join(diff), encoding="utf-8")
    (output_dir / "metadata.json").write_text(
        json.dumps(
            {
                **metadata,
                "fixture_id": fixture_id,
                "expected_sha256": sha256_text(expected),
                "actual_sha256": sha256_text(actual),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return False
