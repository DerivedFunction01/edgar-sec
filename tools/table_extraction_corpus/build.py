"""Build the successor corpus: one context-carrying JSON per filing.

Per filing: catalog-free aggregate from the Archives index, primary
bytes through the rate-limited SEC client, successor extraction under
the annotate policy. Designed to run on Colab High-RAM under a process
pool; each completed filing writes its JSON immediately, so a stopped
run harvests cleanly.
"""

from __future__ import annotations

import argparse
import json
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from tools.table_extraction_corpus.defects import DefectRegister
from tools.table_extraction_corpus.extract import extract_filing
from tools.table_extraction_corpus.fetch import (
    build_aggregate,
    make_client,
    primary_bytes,
)

_WORKER: dict[str, object] = {}


def _worker_init(
    out_dir: str, fixtures_dir: str, tree: str, workers: int, primary_map: str
) -> None:
    _WORKER["client"] = make_client(workers)
    _WORKER["out_dir"] = out_dir
    _WORKER["fixtures"] = fixtures_dir
    _WORKER["tree"] = tree
    _WORKER["primary"] = (
        json.loads(Path(primary_map).read_text(encoding="utf-8")) if primary_map else {}
    )


def _base_record(spec: dict, tree: str) -> dict:
    return {
        "accession": spec["accession"],
        "cik": spec["cik"],
        "form": spec["form"],
        "filing_date": spec["filing_date"],
        "era": spec["era"],
        "is_xbrl": spec["is_xbrl"],
        "filer_category": spec.get("filer_category"),
        "population": "retained-409",
        "status": "ok",
        "error": None,
        "builder": {
            "tool": "tools/table_extraction_corpus",
            "policy": "annotate",
            "tree": tree,
        },
        "geometries": [],
    }


def _process(accession: str) -> dict:
    out_dir = Path(str(_WORKER["out_dir"]))
    target = out_dir / f"{accession}.json"
    if target.exists():
        return {"accession": accession, "status": "skip", "entries": [], "timing": {}}
    spec = json.loads(
        (Path(str(_WORKER["fixtures"])) / f"{accession}.json").read_text(
            encoding="utf-8"
        )
    )
    primary = _WORKER["primary"].get(accession)  # type: ignore[attr-defined]
    if primary:
        spec = {**spec, **primary}
    client = _WORKER["client"]
    started = time.perf_counter()
    timing: dict = {}
    entries: list[dict] = []
    record = _base_record(spec, str(_WORKER["tree"]))
    try:
        fetch_started = time.perf_counter()
        aggregate, source = build_aggregate(client, spec)  # type: ignore[arg-type]
        spec["primary_document"] = (aggregate.primary_document_path or "").rsplit(
            "/", 1
        )[-1]
        spec["primary_source"] = source
        raw = primary_bytes(aggregate) if spec["primary_document"] else None
        timing["fetch_s"] = round(time.perf_counter() - fetch_started, 4)
        if raw is None:
            record["status"] = "no_primary"
            target.write_text(json.dumps(record), encoding="utf-8")
            return {
                "accession": accession,
                "status": "no_primary",
                "entries": entries,
                "timing": timing,
            }
        record, entries, split_timing = extract_filing(
            spec,
            raw,
            str(aggregate.primary_document_path or ""),
            tree=str(_WORKER["tree"]),
        )
        timing.update(split_timing)
    except Exception:  # noqa: BLE001 - per-filing isolation is the design
        record["status"] = "error"
        record["error"] = traceback.format_exc(limit=3)
    timing["total_s"] = round(time.perf_counter() - started, 4)
    target.write_text(json.dumps(record), encoding="utf-8")
    return {
        "accession": accession,
        "status": str(record["status"]),
        "entries": entries,
        "timing": timing,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", required=True)
    parser.add_argument("--primary-map")
    parser.add_argument("--out", required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--accessions-file")
    parser.add_argument("--register")
    parser.add_argument("--summary")
    parser.add_argument("--run-id", default="build")
    parser.add_argument("--tree", default="unknown")
    args = parser.parse_args()

    fixtures_dir = Path(args.fixtures)
    if args.accessions_file:
        accessions = [
            line.strip()
            for line in Path(args.accessions_file)
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
    else:
        accessions = sorted(
            p.stem for p in fixtures_dir.glob("*.json") if "-" in p.stem
        )
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    register = DefectRegister(args.run_id, "step-1-build", "retained-409")
    timings: list[dict] = []
    statuses: dict[str, int] = {}
    wall_started = time.perf_counter()
    done = 0
    with ProcessPoolExecutor(
        max_workers=args.workers,
        initializer=_worker_init,
        initargs=(
            str(out_dir),
            str(fixtures_dir),
            args.tree,
            args.workers,
            args.primary_map or "",
        ),
    ) as pool:
        for outcome in pool.map(_process, accessions, chunksize=1):
            done += 1
            statuses[outcome["status"]] = statuses.get(outcome["status"], 0) + 1
            if outcome["timing"]:
                timings.append({"accession": outcome["accession"], **outcome["timing"]})
            for entry in outcome["entries"]:
                register.add_entry(entry)
            print(
                f"[{done}/{len(accessions)}] {outcome['status']} {outcome['accession']}",
                flush=True,
            )
    wall_s = round(time.perf_counter() - wall_started, 3)
    if args.register:
        register.write(Path(args.register))
    if args.summary:
        Path(args.summary).write_text(
            json.dumps(
                {
                    "run_id": args.run_id,
                    "filings": len(accessions),
                    "statuses": statuses,
                    "wall_s": wall_s,
                    "workers": args.workers,
                    "timings": timings,
                },
                indent=1,
            ),
            encoding="utf-8",
        )
    print(f"build complete: {done} filings in {wall_s}s, statuses={statuses}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
