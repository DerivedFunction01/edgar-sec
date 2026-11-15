"""Build the successor corpus: one context-carrying JSON per filing.

Per filing: catalog-free aggregate from the Archives index, primary
bytes through the rate-limited SEC client, successor extraction under
the annotate policy. Each completed filing writes its JSON at once.
"""

from __future__ import annotations

import argparse
import json
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.forms.families.annual.processing import (
    PROFILE as ANNUAL_PROFILE,
)
from edgar_sec.engine.tables.extraction.profiles import STRATUM_ANNUAL
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.tools.table_extraction_corpus.defects import DefectRegister
from edgar_sec.tools.table_extraction_corpus.extract import extract_filing
from edgar_sec.tools.table_extraction_corpus.fetch import (
    build_aggregate,
    collect_exhibits,
    declared_exhibit_targets,
    make_client,
    primary_bytes,
)

_WORKER: dict[str, object] = {}


# Exhibit coverage is the annual path only (refresh Step 5): the
# registry links exhibits on the annual stratum. No era gate applies.
def annual_stratum(form: str) -> str | None:
    """The registry stratum a filing's form measures on, if annual."""
    return STRATUM_ANNUAL if resolve_alias(form) == ANNUAL_PROFILE.family else None


def _worker_init(
    out_dir: str,
    fixtures_dir: str,
    tree: str,
    workers: int,
    primary_map: str,
    exhibit_types: str,
    exhibit_targets: str,
) -> None:
    _WORKER["client"] = make_client(workers)
    _WORKER["out_dir"] = out_dir
    _WORKER["fixtures"] = fixtures_dir
    _WORKER["tree"] = tree
    _WORKER["primary"] = (
        json.loads(Path(primary_map).read_text(encoding="utf-8")) if primary_map else {}
    )
    _WORKER["exhibit_types"] = tuple(json.loads(exhibit_types)) if exhibit_types else ()
    _WORKER["exhibit_targets"] = json.loads(exhibit_targets) if exhibit_targets else []


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
            "tool": "edgar_sec.tools.table_extraction_corpus",
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
            atomic_write_json(target, record)
            return {
                "accession": accession,
                "status": "no_primary",
                "entries": entries,
                "timing": timing,
            }
        stratum = annual_stratum(str(spec["form"]))
        declared_types = tuple(_WORKER["exhibit_types"])  # type: ignore[arg-type]
        exhibits: tuple[dict, ...] = ()
        if stratum is not None and declared_types:
            exhibit_started = time.perf_counter()
            exhibits = collect_exhibits(aggregate, declared_types)
            timing["exhibit_fetch_s"] = round(time.perf_counter() - exhibit_started, 4)
        record, entries, split_timing = extract_filing(
            spec,
            raw,
            str(aggregate.primary_document_path or ""),
            tree=str(_WORKER["tree"]),
            exhibits=exhibits,
            stratum=stratum,
        )
        if stratum is not None:
            record["builder"]["exhibit_targets"] = list(_WORKER["exhibit_targets"])
        timing.update(split_timing)
    except Exception:  # noqa: BLE001 - per-filing isolation is the design
        record["status"] = "error"
        record["error"] = traceback.format_exc(limit=3)
    timing["total_s"] = round(time.perf_counter() - started, 4)
    atomic_write_json(target, record)
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
    parser.add_argument("--profiles-root")
    args = parser.parse_args()

    exhibit_targets = declared_exhibit_targets(
        STRATUM_ANNUAL, profiles_root=args.profiles_root
    )
    exhibit_types = tuple(target["type"] for target in exhibit_targets)

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

    register = DefectRegister(args.run_id, "corpus-build", "retained-409")
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
            json.dumps(exhibit_types),
            json.dumps(exhibit_targets),
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
        atomic_write_json(
            Path(args.summary),
            {
                "run_id": args.run_id,
                "filings": len(accessions),
                "statuses": statuses,
                "wall_s": wall_s,
                "workers": args.workers,
                "timings": timings,
            },
            canonical=False,
            indent=1,
        )
    print(f"build complete: {done} filings in {wall_s}s, statuses={statuses}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
