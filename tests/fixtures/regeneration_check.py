#!/usr/bin/env python3
"""Verify the untracked fixture sets regenerate faithfully (Step 13).

Rebuilds both fixture sets twice into scratch; checks determinism,
manifest parity, the retired-table pin, and parity with the tree.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = REPO_ROOT / "tests" / "fixtures" / "catalog"
ARCHIVE_DIR = REPO_ROOT / "edgar_sec" / "engine" / "xbrl" / "taxonomy" / "archive"
# The builder CLI's --cache-dir default (build_taxonomy_archive.py).
CACHE_DIR = Path.home() / "workspace" / "xbrl-triage" / "taxonomy-archive-src"

CATALOG_OUTPUTS = (
    "cohort_observations.parquet",
    "cohort_observations_conflicting.parquet",
    "cohort_observations_malformed.parquet",
    "cohort_observations.json.sha256",
    "cohort_observations_plan_fixture.sha256",
    "s1_plan/plan.json",
    "s1_plan/targets/form=10-K/data.parquet",
    "s1_plan/targets/form=8-K/data.parquet",
)
CATALOG_PARQUET = tuple(name for name in CATALOG_OUTPUTS if name.endswith(".parquet"))

# The Step 10 proof's archive total: the builder's row count is pinned.
EXPECTED_ARCHIVE_ROWS = 357_957
# The retired-table content pin is homed in tests.support; both the
# archive test and this harness read it from there.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from tests.support.fixtures import RETIRED_TABLE_SHA256, RETIRED_TABLE_SIZE  # noqa: E402

_PIN_EXCLUDED = ("ifrs", "ffd", "rxp", "cef", "us-gaap-ebp", "invest", "oef", "fnd")


class Report:
    """Collect check outcomes; byte parity is fatal only when required."""

    def __init__(self, require_byte_parity: bool) -> None:
        self.require_byte_parity = require_byte_parity
        self.failures: list[str] = []

    def check(self, label: str, ok: bool, detail: str) -> None:
        """Record a fatal check and print its outcome."""
        print(f"{'ok  ' if ok else 'FAIL'} {label}: {detail}")
        if not ok:
            self.failures.append(label)

    def parity(self, label: str, matched: int, total: int) -> None:
        """Record a byte-parity measure; fatal only when required."""
        ok = matched == total
        print(f"{'ok  ' if ok else 'info'} {label}: {matched}/{total} byte-identical")
        if not ok and self.require_byte_parity:
            self.failures.append(label)


def _sha256(path: Path) -> str:
    """Hex sha256 of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_parity(report: Report, label: str, catalog_dir: Path) -> None:
    """Check a catalog set's manifests against its own parquet bytes."""
    manifest = json.loads((catalog_dir / "cohort_observations.json.sha256").read_text())
    for entry in manifest["fixtures"]:
        name = entry["name"]
        actual = _sha256(catalog_dir / f"{name}.parquet")
        report.check(
            f"{label} manifest parity {name}",
            actual == entry["sha256"],
            "recorded sha256 matches the parquet bytes",
        )
    plan = json.loads(
        (catalog_dir / "cohort_observations_plan_fixture.sha256").read_text()
    )
    for form_key, recorded in plan.items():
        part = catalog_dir / "s1_plan" / "targets" / form_key / "data.parquet"
        actual = _sha256(part)
        report.check(
            f"{label} manifest parity {form_key}",
            actual == recorded,
            "recorded sha256 matches the parquet bytes",
        )


def _catalog_leg(report: Report, scratch: Path) -> None:
    """Rebuild the catalog fixtures twice; compare runs and the tree set."""
    spec = importlib.util.spec_from_file_location(
        "_author_cohort_fixtures", CATALOG_DIR / "_author_cohort_fixtures.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runs: list[Path] = []
    for index in (0, 1):
        out_dir = scratch / f"catalog-{index}"
        out_dir.mkdir(parents=True)
        module.FIXTURES = out_dir
        with contextlib.redirect_stdout(io.StringIO()):
            module.main()
        runs.append(out_dir)
    run_a = runs[0]
    deterministic = sum(
        _sha256(run_a / name) == _sha256(runs[1] / name) for name in CATALOG_OUTPUTS
    )
    report.check(
        "catalog determinism",
        deterministic == len(CATALOG_OUTPUTS),
        f"{deterministic}/{len(CATALOG_OUTPUTS)} outputs byte-identical across runs",
    )
    _manifest_parity(report, "catalog regenerated", run_a)
    present = [name for name in CATALOG_OUTPUTS if (CATALOG_DIR / name).is_file()]
    if len(present) < len(CATALOG_OUTPUTS):
        print(
            f"info catalog parity vs tree: tree set incomplete "
            f"({len(present)}/{len(CATALOG_OUTPUTS)} present), tree legs skipped"
        )
        return
    _manifest_parity(report, "catalog tree", CATALOG_DIR)
    content = sum(
        pq.read_table(run_a / name).equals(pq.read_table(CATALOG_DIR / name))
        for name in CATALOG_PARQUET
    )
    report.check(
        "catalog content parity vs tree",
        content == len(CATALOG_PARQUET),
        f"{content}/{len(CATALOG_PARQUET)} parquet outputs row-identical to the tree",
    )
    report.check(
        "catalog plan.json parity vs tree",
        (run_a / "s1_plan" / "plan.json").read_bytes()
        == (CATALOG_DIR / "s1_plan" / "plan.json").read_bytes(),
        "plan.json byte-identical to the tree",
    )
    matched = sum(
        _sha256(run_a / name) == _sha256(CATALOG_DIR / name) for name in CATALOG_OUTPUTS
    )
    report.parity("catalog byte parity vs tree", matched, len(CATALOG_OUTPUTS))


def _retired_table_pin(report: Report, archive_dir: Path) -> None:
    """Reproduce the retired-table content pin from a regenerated set."""
    from edgar_sec.engine.xbrl.taxonomy.archive import (
        CURRENT_SLICES,
        TAXONOMY_PREFIXES,
    )

    table: dict[str, str] = {}
    for taxonomy, version in CURRENT_SLICES:
        if taxonomy in _PIN_EXCLUDED:
            continue
        rows = pq.read_table(archive_dir / taxonomy / f"{version}.parquet").to_pylist()
        for row in rows:
            if row["item_type"] is not None:
                table[f"{TAXONOMY_PREFIXES[taxonomy]}:{row['name']}"] = row["item_type"]
    canonical = json.dumps(table, indent=1, sort_keys=True) + "\n"
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    report.check(
        "archive retired-table content pin",
        len(table) == RETIRED_TABLE_SIZE and digest == RETIRED_TABLE_SHA256,
        f"{len(table)} entries, sha256 "
        f"{'matches' if digest == RETIRED_TABLE_SHA256 else 'DIFFERS'}",
    )


def _archive_leg(report: Report, scratch: Path) -> None:
    """Rebuild the taxonomy archive twice; compare runs and the tree set."""
    from edgar_sec.tools.xbrl_discovery.build_taxonomy_archive import (
        _releases,
        build,
    )

    slices = [f"{taxonomy}/{version}.parquet" for taxonomy, version, _ in _releases()]
    runs: list[Path] = []
    for index in (0, 1):
        out_dir = scratch / f"archive-{index}"
        with contextlib.redirect_stdout(io.StringIO()):
            total = build(CACHE_DIR, out_dir)
        report.check(
            f"archive run {index} row total",
            total == EXPECTED_ARCHIVE_ROWS,
            f"{total} rows (pinned {EXPECTED_ARCHIVE_ROWS})",
        )
        runs.append(out_dir)
    run_a = runs[0]
    deterministic = sum(
        _sha256(run_a / name) == _sha256(runs[1] / name) for name in slices
    )
    report.check(
        "archive determinism",
        deterministic == len(slices),
        f"{deterministic}/{len(slices)} slices byte-identical across runs",
    )
    _retired_table_pin(report, run_a)
    present = [name for name in slices if (ARCHIVE_DIR / name).is_file()]
    if not present:
        print("info archive parity vs tree: tree set absent, parity legs skipped")
        return
    content = sum(
        pq.read_table(run_a / name).equals(pq.read_table(ARCHIVE_DIR / name))
        for name in present
    )
    report.check(
        "archive content parity vs tree",
        content == len(present),
        f"{content}/{len(present)} present tree slices row-identical",
    )
    matched = sum(
        _sha256(run_a / name) == _sha256(ARCHIVE_DIR / name) for name in present
    )
    report.parity("archive byte parity vs tree", matched, len(present))


def main() -> int:
    """Run the regeneration checks; exit 1 when any fatal check fails."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--leg", choices=("all", "catalog", "archive"), default="all")
    parser.add_argument(
        "--require-byte-parity",
        action="store_true",
        help="fail when a regenerated set is not byte-identical to the tree set",
    )
    args = parser.parse_args()
    report = Report(require_byte_parity=args.require_byte_parity)
    scratch = Path(tempfile.mkdtemp(prefix="regeneration-check-"))
    print(f"scratch: {scratch}")
    try:
        if args.leg in ("all", "catalog"):
            _catalog_leg(report, scratch)
        if args.leg in ("all", "archive"):
            _archive_leg(report, scratch)
    finally:
        if report.failures:
            print(f"scratch kept for inspection: {scratch}")
        else:
            shutil.rmtree(scratch, ignore_errors=True)
    if report.failures:
        print(f"FAILED: {len(report.failures)} check(s): {', '.join(report.failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
