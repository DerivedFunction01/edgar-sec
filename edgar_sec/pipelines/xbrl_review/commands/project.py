"""Project published catalog plans or uniform datasets into resumable XBRL runs."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.engine.xbrl.solve.solver import SOLVER_FINGERPRINT
from edgar_sec.foundation.runtime.paths import resolve_paths
from edgar_sec.foundation.runtime.settings import resolve_settings
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.dag.publication import read_pointer
from edgar_sec.infra.storage.duckdb import connect, copy_query_to_parquet, sql_literal
from edgar_sec.pipelines.xbrl_review.paths import (
    PLAN_TARGETS_DIR,
    SOLVED_NODES_FILE,
    resolve_filing_catalog_paths,
    xbrl_paths,
    xbrl_run_paths,
)
from edgar_sec.pipelines.xbrl_review.schemas import WORK_ORDER_SCHEMA


def resolve_artifacts_root(value: str | Path | None = None) -> Path:
    """Resolve artifacts root directory."""
    if value:
        return Path(value).expanduser().resolve()
    return resolve_paths().artifacts_root.resolve()


def project_xbrl_run(
    *,
    catalog_plan_id: str | None = None,
    dataset_path: Path | str | None = None,
    queries_path: Path | str | None = None,
    artifacts_root: Path | str | None = None,
    base_snapshot_id: str | None = None,
    branch_name: str = "main",
    chunk_size: int | None = None,
    explicit_refresh: bool = False,
) -> dict[str, Any]:
    """Project input catalog plan or dataset into a resumable XBRL work order."""
    root = resolve_artifacts_root(artifacts_root)
    paths = xbrl_paths(root)
    settings = resolve_settings()
    effective_chunk_size = (
        int(chunk_size)
        if chunk_size is not None
        else int(settings["runtime.chunk_size"])
    )

    now = datetime.now(timezone.utc)
    run_id = f"run-{now.strftime('%Y%m%d_%H%M%S')}"
    run_paths = xbrl_run_paths(root, run_id)
    run_paths.run_root.mkdir(parents=True, exist_ok=True)

    with connect() as con:
        if catalog_plan_id is not None:
            cat_paths = resolve_filing_catalog_paths(root)
            plan_dir = cat_paths.plan_dir(catalog_plan_id)
            if not plan_dir.is_dir():
                raise ValueError(f"catalog plan not found: {catalog_plan_id}")
            targets_dir = plan_dir / PLAN_TARGETS_DIR
            target_glob = str(targets_dir / "**" / "*.parquet")
            con.execute(
                f"CREATE TEMP TABLE candidate_accessions AS "
                f"SELECT DISTINCT accession, form, filing_date, cik, report_date "
                f"FROM read_parquet({sql_literal(target_glob)}, hive_partitioning=false)"
            )
        elif dataset_path is not None:
            dsp = Path(dataset_path).resolve()
            if not dsp.is_file() and not dsp.is_dir():
                raise ValueError(f"dataset path not found: {dataset_path}")
            if dsp.suffix == ".json":
                con.execute(
                    f"CREATE TEMP TABLE candidate_accessions AS "
                    f"SELECT DISTINCT "
                    f"accession::VARCHAR AS accession, "
                    f"coalesce(form, '')::VARCHAR AS form, "
                    f"coalesce(filing_date, '')::VARCHAR AS filing_date, "
                    f"coalesce(try_cast(cik as BIGINT), 0)::BIGINT AS cik, "
                    f"coalesce(period, report_date, fy, '')::VARCHAR AS report_date "
                    f"FROM read_json_auto({sql_literal(str(dsp))}, "
                    f"columns={{'accession': 'VARCHAR', 'form': 'VARCHAR', 'filing_date': 'VARCHAR', "
                    f"'cik': 'VARCHAR', 'period': 'VARCHAR', 'report_date': 'VARCHAR', 'fy': 'VARCHAR'}}) "
                    f"WHERE accession IS NOT NULL"
                )
            else:
                con.execute(
                    f"CREATE TEMP TABLE candidate_accessions AS "
                    f"SELECT DISTINCT accession, form, filing_date, cik, report_date "
                    f"FROM read_parquet({sql_literal(str(dsp))})"
                )
        else:
            raise ValueError("either catalog_plan_id or dataset_path must be provided")

        resolved_base_id = base_snapshot_id
        if resolved_base_id is None and branch_name:
            ptr = read_pointer(paths.snapshots_root, branch_name=branch_name)
            if ptr is not None:
                resolved_base_id = str(ptr.get("snapshot_id", ""))

        has_base_nodes = False
        if resolved_base_id and not explicit_refresh:
            base_file = paths.snapshots_root / resolved_base_id / SOLVED_NODES_FILE
            has_base_nodes = base_file.is_file()

        if has_base_nodes and resolved_base_id:
            base_p = paths.snapshots_root / resolved_base_id / SOLVED_NODES_FILE
            con.execute(
                f"CREATE TEMP TABLE delta_work AS "
                f"SELECT c.* FROM candidate_accessions c "
                f"ANTI JOIN (SELECT DISTINCT accession FROM read_parquet({sql_literal(str(base_p))})) s "
                f"ON c.accession = s.accession ORDER BY c.accession"
            )
        else:
            con.execute(
                "CREATE TEMP TABLE delta_work AS "
                "SELECT * FROM candidate_accessions ORDER BY accession"
            )

        copy_query_to_parquet(
            con,
            "SELECT * FROM candidate_accessions ORDER BY accession",
            run_paths.cohort_accessions_path(),
        )
        copy_query_to_parquet(
            con,
            "SELECT * FROM delta_work ORDER BY accession",
            run_paths.work_order_path(),
        )

        cohort_rows = con.execute(
            "SELECT count(*) FROM candidate_accessions"
        ).fetchone()[0]
        work_rows = con.execute("SELECT count(*) FROM delta_work").fetchone()[0]

    manifest = {
        "run_id": run_id,
        "source_type": "catalog_plan" if catalog_plan_id else "dataset",
        "source_ref": catalog_plan_id or str(dataset_path),
        "queries_path": str(queries_path) if queries_path else None,
        "base_snapshot_id": resolved_base_id,
        "branch": branch_name,
        "cohort_accession_rows": int(cohort_rows),
        "work_order_rows": int(work_rows),
        "solver_fingerprint": SOLVER_FINGERPRINT,
        "chunk_size": effective_chunk_size,
    }
    atomic_write_json(run_paths.projection_manifest_path(), manifest, indent=2)
    atomic_write_json(
        run_paths.run_manifest_path(),
        {
            "run_id": run_id,
            "created_at": now.isoformat(),
            "chunk_size": effective_chunk_size,
            "work_order_rows": int(work_rows),
            "status": "projected",
        },
        indent=2,
    )
    return manifest


def cmd_project(args: argparse.Namespace) -> int:
    """CLI handler for project command."""
    manifest = project_xbrl_run(
        catalog_plan_id=getattr(args, "catalog_plan", None),
        dataset_path=getattr(args, "dataset", None),
        queries_path=getattr(args, "queries", None),
        artifacts_root=getattr(args, "artifacts_root", None),
        base_snapshot_id=getattr(args, "base_snapshot_id", None),
        branch_name=getattr(args, "branch", "main"),
        chunk_size=getattr(args, "chunk_size", None),
        explicit_refresh=bool(getattr(args, "explicit_refresh", False)),
    )
    if getattr(args, "json", False):
        print(json.dumps(manifest, sort_keys=True))
    else:
        print(
            f"Projected run {manifest['run_id']}: "
            f"{manifest['cohort_accession_rows']} accessions, "
            f"{manifest['work_order_rows']} work items, "
            f"chunk size {manifest['chunk_size']}, branch {manifest['branch']}, "
            f"base {manifest['base_snapshot_id'] or '(none)'}"
        )
    return 0


__all__ = ["cmd_project", "project_xbrl_run", "resolve_artifacts_root"]
