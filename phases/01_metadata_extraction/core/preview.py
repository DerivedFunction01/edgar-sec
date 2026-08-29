"""Bounded SEC-backed preview orchestration."""

from __future__ import annotations

import json
import logging

from defs.runtime.paths import resolve_paths

from .config import RunOptions
from .input_manifest import read_input_manifest
from .storage import make_checkpoint_store

logger = logging.getLogger("metadata.preview")


def preview_sample(options: RunOptions, sample_size: int = 3) -> dict:
    """Fetch a small sample and write it under the shared transient preview root."""
    from .application import _build_client, _fetch_and_normalize, utc_now_iso

    rows, _report = read_input_manifest(
        options.input_path, limit=max(sample_size, options.limit or 0)
    )
    sample = rows[:sample_size]
    client = _build_client(options)
    snapshot_id = f"preview-{utc_now_iso()}"
    summaries = []
    completed_rows = []
    for target in sample:
        try:
            row = _fetch_and_normalize(client, target, snapshot_id)
            completed_rows.append(row)
            forms = sorted({f.get("form") for f in row["filings"] if f.get("form")})
            summaries.append(
                {
                    "cik": target.cik_padded,
                    "input_name": target.name,
                    "sec_name": row["identity"]["name"],
                    "status": row["status"],
                    "error": row["error"],
                    "recent_filings": sum(
                        1 for f in row["filings"] if f.get("source_section") == "recent"
                    ),
                    "historical_files": row["historical_files_total"],
                    "combined_filing_records": len(row["filings"]),
                    "forms_found": forms,
                    "anomalies": row["anomalies"],
                }
            )
        except Exception as exc:
            logger.exception("preview failed for %s", target.cik_padded)
            summaries.append(
                {
                    "cik": target.cik_padded,
                    "input_name": target.name,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    preview_root = resolve_paths("metadata").preview_root
    preview_root.mkdir(parents=True, exist_ok=True)
    out_json = str(preview_root / "preview_summary.json")
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump(
            {"sample": summaries, "metrics": client.http.metrics.snapshot()},
            fh,
            indent=2,
        )

    output_rows = [row for row in completed_rows if row.get("status") != "failed"]
    sample_path = None
    if output_rows:
        sample_path = str(preview_root / f"preview_sample.{options.storage_format}")
        make_checkpoint_store(options, root=str(preview_root)).finalize(
            output_rows, sample_path
        )

    for item in summaries:
        print(
            f"{item['cik']}  {str(item.get('sec_name') or item.get('input_name'))[:40]:40s} "
            f"status={item['status']} filings={item.get('combined_filing_records', 0)} "
            f"hist_files={item.get('historical_files', 0)}"
            + (f" error={item['error']}" if item.get("error") else "")
        )
    return {
        "sample": summaries,
        "metrics": client.http.metrics.snapshot(),
        "summary_path": out_json,
        "sample_artifact": sample_path,
    }
