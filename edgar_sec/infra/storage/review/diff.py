"""Comparison and diff engine for review runs and cases."""

from __future__ import annotations

import difflib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from edgar_sec.infra.storage.atomic import atomic_write_json, atomic_write_text
from edgar_sec.infra.storage.duckdb import connect

from .adapter import ReviewAdapter
from .models import CaseDiff, ComponentCount, DiffSummary
from .paths import ReviewPaths


def diff_text(
    base_text: str,
    new_text: str,
    fromfile: str = "base",
    tofile: str = "new",
) -> tuple[int, int, str]:
    """Compute added count, removed count, and unified diff text."""
    base_lines = base_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    diff = list(
        difflib.unified_diff(
            base_lines,
            new_lines,
            fromfile=fromfile,
            tofile=tofile,
        )
    )
    if not diff:
        return 0, 0, ""
    added = sum(
        1 for line in diff if line.startswith("+") and not line.startswith("+++")
    )
    removed = sum(
        1 for line in diff if line.startswith("-") and not line.startswith("---")
    )
    return added, removed, "".join(diff)


def flatten_json(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Recursively flatten nested dicts and lists into bracketed key paths."""
    flattened: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_key = f"{prefix}.{k}" if prefix else str(k)
            flattened.update(flatten_json(v, new_key))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            new_key = f"{prefix}[{idx}]"
            flattened.update(flatten_json(item, new_key))
    else:
        flattened[prefix] = obj
    return flattened


def diff_json(
    base_obj: Any,
    new_obj: Any,
    label: str = "",
) -> tuple[int, int, str]:
    """Compute added, removed count, and unified patch text for two JSON objects."""
    base_flat = flatten_json(base_obj)
    new_flat = flatten_json(new_obj)
    added_keys = [k for k in sorted(new_flat) if k not in base_flat]
    removed_keys = [k for k in sorted(base_flat) if k not in new_flat]
    modified_keys = [
        k for k in sorted(base_flat) if k in new_flat and base_flat[k] != new_flat[k]
    ]

    lines: list[str] = []
    if label:
        lines.append(f"--- {label} (base)")
        lines.append(f"+++ {label} (new)")
    for k in removed_keys:
        lines.append(f"- {k}: {json.dumps(base_flat[k], sort_keys=True)}")
    for k in added_keys:
        lines.append(f"+ {k}: {json.dumps(new_flat[k], sort_keys=True)}")
    for k in modified_keys:
        lines.append(f"- {k}: {json.dumps(base_flat[k], sort_keys=True)}")
        lines.append(f"+ {k}: {json.dumps(new_flat[k], sort_keys=True)}")

    added_total = len(added_keys) + len(modified_keys)
    removed_total = len(removed_keys) + len(modified_keys)
    patch_text = "\n".join(lines) + ("\n" if lines else "")
    return added_total, removed_total, patch_text


def diff_dataset(base_path: Path, new_path: Path) -> tuple[int, int, str]:
    """Compare two tabular datasets using DuckDB set operations."""
    if not base_path.is_file() and not new_path.is_file():
        return 0, 0, ""
    if not base_path.is_file():
        count = _count_dataset_rows(new_path)
        return count, 0, f"+ {new_path.name}: +{count} rows (new file)\n"
    if not new_path.is_file():
        count = _count_dataset_rows(base_path)
        return 0, count, f"- {base_path.name}: -{count} rows (removed file)\n"

    base_str = str(base_path)
    new_str = str(new_path)
    is_csv = base_path.suffix.lower() == ".csv"
    query = (
        "SELECT count(*) FROM ("
        "SELECT * FROM read_csv_auto(?) EXCEPT SELECT * FROM read_csv_auto(?)"
        ")"
        if is_csv
        else (
            "SELECT count(*) FROM ("
            "SELECT * FROM read_parquet(?) EXCEPT SELECT * FROM read_parquet(?)"
            ")"
        )
    )

    with connect() as con:
        added_count = con.execute(query, [new_str, base_str]).fetchone()[0]
        removed_count = con.execute(query, [base_str, new_str]).fetchone()[0]

    lines: list[str] = []
    if added_count > 0 or removed_count > 0:
        lines.append(f"--- {base_path.name} (base)")
        lines.append(f"+++ {new_path.name} (new)")
        lines.append(f"@@ row changes: +{added_count} / -{removed_count} @@")
    patch = "\n".join(lines) + ("\n" if lines else "")
    return added_count, removed_count, patch


def _count_dataset_rows(path: Path) -> int:
    query = (
        "SELECT count(*) FROM read_csv_auto(?)"
        if path.suffix.lower() == ".csv"
        else "SELECT count(*) FROM read_parquet(?)"
    )
    with connect() as con:
        return con.execute(query, [str(path)]).fetchone()[0]


def _discover_cases(run_dir: Path) -> dict[str, Path]:
    paths = ReviewPaths(run_dir)
    cases_dir = paths.cases_dir if paths.cases_dir.is_dir() else run_dir
    cases: dict[str, Path] = {}
    for entry in cases_dir.iterdir():
        if entry.is_dir():
            cases[entry.name] = entry
    return cases


def compare_review_runs(
    base_dir: Path,
    new_dir: Path,
    output_dir: Path,
    adapter: ReviewAdapter,
    max_display: int = 20,
) -> DiffSummary:
    """Compare two review runs, writing report and patches to output_dir."""
    base_cases = _discover_cases(base_dir)
    new_cases = _discover_cases(new_dir)
    all_case_ids = sorted(set(base_cases.keys()) | set(new_cases.keys()))

    diffs: list[CaseDiff] = []
    for cid in all_case_ids:
        b_path = base_cases.get(cid)
        n_path = new_cases.get(cid)
        diffs.append(adapter.compare_case(cid, b_path, n_path))

    unchanged = sum(1 for d in diffs if d.status == "unchanged")
    changed = sum(1 for d in diffs if d.status == "changed")
    added = sum(1 for d in diffs if d.status == "added")
    removed = sum(1 for d in diffs if d.status == "removed")

    comp_map: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for d in diffs:
        if d.details and d.status == "changed":
            comp = d.details.split()[0] if d.details else "unknown"
            comp_map[comp].append((d.added_count, d.removed_count))

    breakdown_list = [
        (
            k,
            ComponentCount(
                affected_cases=len(v),
                added_total=sum(item[0] for item in v),
                removed_total=sum(item[1] for item in v),
            ),
        )
        for k, v in sorted(comp_map.items())
    ]

    summary = DiffSummary(
        base_run=str(base_dir),
        new_run=str(new_dir),
        total_cases=len(all_case_ids),
        unchanged_count=unchanged,
        changed_count=changed,
        added_count=added,
        removed_count=removed,
        component_breakdown=tuple(breakdown_list),
        case_diffs=tuple(diffs),
    )

    _write_output_artifacts(summary, output_dir, max_display)
    return summary


def _write_output_artifacts(
    summary: DiffSummary,
    output_dir: Path,
    max_display: int,
) -> None:
    paths = ReviewPaths(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    text = format_summary_text(summary, max_display=max_display)
    atomic_write_text(paths.summary_file, text)

    manifest_data = {
        "base_run": summary.base_run,
        "new_run": summary.new_run,
        "total_cases": summary.total_cases,
        "unchanged_count": summary.unchanged_count,
        "changed_count": summary.changed_count,
        "added_count": summary.added_count,
        "removed_count": summary.removed_count,
        "cases": [
            {
                "case_id": d.case_id,
                "status": d.status,
                "added_count": d.added_count,
                "removed_count": d.removed_count,
                "details": d.details,
            }
            for d in summary.case_diffs
        ],
    }
    atomic_write_json(paths.diff_manifest_file, manifest_data)

    for d in summary.case_diffs:
        if d.patch:
            paths.patches_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_text(paths.patch_file(d.case_id), d.patch)


def format_summary_text(summary: DiffSummary, max_display: int = 20) -> str:
    """Format human-readable summary text with bounded case display."""
    lines = [
        "========================================================================",
        "   Parser Review Comparison Report",
        "========================================================================",
        f"Base Run:       {summary.base_run}",
        f"New Run:        {summary.new_run}",
        f"Cases Compared: {summary.total_cases}",
        "",
        "Summary:",
        f"  Unchanged:    {summary.unchanged_count}",
        f"  Changed:      {summary.changed_count}",
        f"  Added:        {summary.added_count}",
        f"  Removed:      {summary.removed_count}",
    ]

    if summary.component_breakdown:
        lines.append("")
        lines.append("Breakdown by Component:")
        for name, count in summary.component_breakdown:
            lines.append(
                f"  * {name}: {count.affected_cases} cases affected "
                f"(+{count.added_total} / -{count.removed_total})"
            )

    changed_diffs = [d for d in summary.case_diffs if d.status != "unchanged"]
    if changed_diffs:
        lines.append("")
        count_to_show = min(len(changed_diffs), max_display)
        lines.append(
            f"Changed Cases (showing first {count_to_show} of {len(changed_diffs)}):"
        )
        for d in changed_diffs[:count_to_show]:
            detail = f": {d.details}" if d.details else f" ({d.status})"
            lines.append(f"  * {d.case_id}{detail}")
        if len(changed_diffs) > max_display:
            remaining = len(changed_diffs) - max_display
            lines.append(
                f"  ... and {remaining} additional cases. Full list in: {ReviewPaths(Path()).diff_manifest_file.name}"
            )

    lines.append(
        "========================================================================"
    )
    lines.append("")
    return "\n".join(lines)
