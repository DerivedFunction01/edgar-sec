"""Adjudicated-specimen fixture rebuild over the corpus build path.

Two stages: fixtures built through the corpus aggregate route and
matched to adjudicated tables by normalized cell overlap, then the
document cure rebuilding weak members from their own documents.
"""

from __future__ import annotations

import argparse
import json
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from edgar_sec.domain.sec_urls import archives_url
from edgar_sec.foundation.runtime.resources import derive_resources
from edgar_sec.foundation.text.patterns import RE_NON_ALNUM
from edgar_sec.infra.storage.atomic import atomic_write_json, atomic_write_text
from edgar_sec.tools.table_extraction_corpus.build import _base_record
from edgar_sec.tools.table_extraction_corpus.extract import extract_filing
from edgar_sec.tools.table_extraction_corpus.fetch import (
    build_aggregate,
    make_client,
    primary_bytes,
)

_AGGREGATE_MIN_CELLS = 5
_CURE_MIN_CELLS = 3
_WEAK_SCORE = 0.5
_CURE_SCORE = 0.9
_FETCH_ATTEMPTS = 3

_WORKER: dict[str, object] = {}


def norm_cell(cell: str) -> str:
    """One table cell normalized for overlap matching."""
    return RE_NON_ALNUM.sub("", str(cell).lower())


def cell_set(rows) -> set[str]:
    """The normalized cell set of one table's rows."""
    out: set[str] = set()
    for row in rows or []:
        for cell in row or []:
            normalized = norm_cell(cell)
            if len(normalized) >= 4:
                out.add(normalized)
    return out


def load_specimens(path: str | Path) -> dict:
    """Read a specimens file naming rounds and frame members."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _adjudication(inputs: Path, name: str) -> dict[str, dict]:
    items = json.loads((inputs / name).read_text(encoding="utf-8"))
    return {item["adsh"]: item for item in items}


def _targets(inputs: Path, name: str) -> dict[str, list]:
    """Adjudicated tables per accession, from a tables dump.

    A dump item carries either its one table's rows or a tables
    list; the multi form extends, the single form is last-wins.
    """
    out: dict[str, list] = {}
    items = json.loads((inputs / name).read_text(encoding="utf-8"))
    for item in items:
        if item.get("tables") is not None:
            out.setdefault(item["adsh"], []).extend(
                table.get("rows") or [] for table in item["tables"] or []
            )
        else:
            out[item["adsh"]] = [item.get("rows") or []]
    return out


def _round_spec(accession: str, item: dict, era: str) -> dict:
    return {
        "accession": accession,
        "cik": str(int(item["ciks"][0])),
        "form": item["form"],
        "filing_date": item["file_date"],
        "era": era,
        "is_xbrl": False,
        "filer_category": None,
    }


def specimen_jobs(
    specimens: dict, inputs: Path
) -> tuple[list[tuple[str, dict]], list[str]]:
    """Build jobs for every specimen, plus the round accessions.

    Rounds in file order, then the frame members; specs derive
    from the adjudication items and the frame specs file.
    """
    jobs: list[tuple[str, dict]] = []
    round_accessions: list[str] = []
    for round_ in specimens["rounds"]:
        adjudication = _adjudication(inputs, round_["adjudication"])
        for accession in round_["accessions"]:
            jobs.append(
                (
                    accession,
                    _round_spec(accession, adjudication[accession], round_["era"]),
                )
            )
            round_accessions.append(accession)
    frame_specs = json.loads(
        (inputs / specimens["frame"]["specs"]).read_text(encoding="utf-8")
    )
    for bare in specimens["frame"]["bares"]:
        accession = bare.rsplit(":", 1)[0]
        fs = frame_specs[accession]
        jobs.append(
            (
                accession,
                {
                    "accession": accession,
                    "cik": fs["cik"],
                    "form": fs["form"],
                    "filing_date": fs["filing_date"],
                    "era": fs["era"],
                    "is_xbrl": False,
                    "filer_category": None,
                },
            )
        )
    return jobs, round_accessions


def _worker_init(fixtures: str, tree: str, workers: int) -> None:
    _WORKER["client"] = make_client(workers)
    _WORKER["fixtures"] = fixtures
    _WORKER["tree"] = tree


def _build_one(job: tuple[str, dict]) -> tuple[str, dict]:
    accession, spec = job
    fixtures = Path(str(_WORKER["fixtures"]))
    tree = str(_WORKER["tree"])
    target = fixtures / f"{accession}.json"
    if target.exists():
        record = json.loads(target.read_text(encoding="utf-8"))
        return accession, {
            "status": record.get("status"),
            "geometries": len(record.get("geometries") or []),
        }
    record = _base_record(spec, tree)
    try:
        aggregate, source = build_aggregate(_WORKER["client"], spec)  # type: ignore[arg-type]
        spec["primary_document"] = (aggregate.primary_document_path or "").rsplit(
            "/", 1
        )[-1]
        spec["primary_source"] = source
        raw = primary_bytes(aggregate) if spec["primary_document"] else None
        if raw is None:
            record["status"] = "no_primary"
        else:
            record, _entries, _timing = extract_filing(
                spec,
                raw,
                str(aggregate.primary_document_path or ""),
                tree=tree,
            )
    except Exception:  # noqa: BLE001 - per-filing isolation is the design
        record["status"] = "error"
        record["error"] = traceback.format_exc(limit=3)
    atomic_write_text(target, json.dumps(record))
    return accession, {
        "status": record.get("status"),
        "geometries": len(record.get("geometries") or []),
    }


def match_members(
    fixtures_dir: Path,
    targets_by_accession: dict[str, list],
    accessions: list[str],
    min_cells: int,
) -> dict[str, dict]:
    """Match each member's adjudicated table to a fixture geometry.

    Scores are target-cell coverage per geometry; the best-scoring
    geometry wins, first maximal in table-index order.
    """
    match: dict[str, dict] = {}
    for accession in accessions:
        targets = targets_by_accession.get(accession)
        fixture = fixtures_dir / f"{accession}.json"
        if targets is None or not fixture.exists():
            match[accession] = {"status": "no_dump_or_fixture"}
            continue
        doc = json.loads(fixture.read_text(encoding="utf-8"))
        geoms = sorted(
            doc.get("geometries") or [], key=lambda g: g.get("table_index") or 0
        )
        if not geoms:
            match[accession] = {"status": "no_geometries"}
            continue
        gsets = [(g.get("table_index"), cell_set(g.get("rows"))) for g in geoms]
        best: tuple[float, object, int] | None = None
        per_geom_best: dict[object, float] = {}
        for target_idx, target_rows in enumerate(targets):
            tcells = cell_set(target_rows)
            if len(tcells) < min_cells:
                continue
            for table_index, gcells in gsets:
                if not gcells:
                    continue
                score = len(tcells & gcells) / len(tcells)
                if score > per_geom_best.get(table_index, -1.0):
                    per_geom_best[table_index] = score
                if best is None or score > best[0]:
                    best = (score, table_index, target_idx)
        if best is None:
            match[accession] = {"status": "no_scorable_target"}
            continue
        ranked = sorted(per_geom_best.values(), reverse=True)
        match[accession] = {
            "status": "matched",
            "table_index": best[1],
            "bare": f"{accession}:{best[1]}",
            "score": round(best[0], 3),
            "target_idx": best[2],
            "margin": round(best[0] - (ranked[1] if len(ranked) > 1 else 0.0), 3),
            "n_geometries": len(geoms),
        }
    return match


def _bases(specimens: dict, match: dict, round_accessions: list[str]) -> dict:
    bares = list(specimens["frame"]["bares"])
    for accession in round_accessions:
        entry = match.get(accession) or {}
        if entry.get("status") == "matched":
            bares.append(entry["bare"])
    return {
        "members": {
            specimens["stratum"]: {
                specimens["family"]: [{"specimen_id": b} for b in bares]
            }
        }
    }


def _round_targets(specimens: dict, inputs: Path) -> dict[str, list]:
    targets: dict[str, list] = {}
    for round_ in specimens["rounds"]:
        targets.update(_targets(inputs, round_["tables"]))
    return targets


def stage_aggregate(
    inputs: Path,
    specimens: dict,
    work: Path,
    out: Path,
    *,
    tree: str,
    workers: int | None = None,
) -> dict:
    """Build every specimen fixture and match the round members."""
    fixtures = work / "fixtures"
    fixtures.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    jobs, round_accessions = specimen_jobs(specimens, inputs)
    resolved = workers if workers and workers > 0 else derive_resources().workers
    index: dict[str, dict] = {}
    if resolved > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(
            max_workers=resolved,
            initializer=_worker_init,
            initargs=(str(fixtures), tree, resolved),
        ) as pool:
            for accession, entry in pool.map(_build_one, jobs, chunksize=1):
                index[accession] = entry
    else:
        _worker_init(str(fixtures), tree, 1)
        for job in jobs:
            accession, entry = _build_one(job)
            index[accession] = entry
    match = match_members(
        fixtures,
        _round_targets(specimens, inputs),
        round_accessions,
        _AGGREGATE_MIN_CELLS,
    )
    bases = _bases(specimens, match, round_accessions)
    atomic_write_json(out / "bases.json", bases, canonical=False, indent=1)
    atomic_write_json(out / "match-report.json", match, canonical=False, indent=1)
    atomic_write_json(out / "fixture-index.json", index, canonical=False, indent=1)
    weak = {
        a: m
        for a, m in match.items()
        if m.get("status") == "matched" and m["score"] < _WEAK_SCORE
    }
    return {
        "fixtures_ok": sum(1 for v in index.values() if v["geometries"] > 0),
        "fixtures_total": len(index),
        "matched": sum(1 for m in match.values() if m.get("status") == "matched"),
        "weak_matches": len(weak),
        "bases_members": len(
            bases["members"][specimens["stratum"]][specimens["family"]]
        ),
    }


def _fetch_document(client, cik: str, accession: str, filename: str) -> bytes | None:
    url = archives_url(cik, accession, filename)
    for attempt in range(_FETCH_ATTEMPTS):
        try:
            return client.get_bytes(url)
        except Exception:  # noqa: BLE001 - a failed fetch retries, then records
            if attempt == _FETCH_ATTEMPTS - 1:
                return None
            time.sleep(2 * (attempt + 1))
    return None


def stage_cure(
    inputs: Path,
    specimens: dict,
    work: Path,
    out: Path,
    *,
    tree: str,
    prior_match: dict,
) -> dict:
    """Rebuild weak members from their own documents; re-match all."""
    fixtures = work / "fixtures"
    out.mkdir(parents=True, exist_ok=True)
    jobs, round_accessions = specimen_jobs(specimens, inputs)
    have = {p.stem for p in fixtures.glob("*.json")}
    if len(have) != len(jobs):
        raise ValueError(f"expected {len(jobs)} staged fixtures, found {len(have)}")
    adjudications = [
        _adjudication(inputs, round_["adjudication"]) for round_ in specimens["rounds"]
    ]
    rebuild = [
        accession
        for accession in round_accessions
        if (prior_match.get(accession) or {}).get("status") != "matched"
        or (prior_match[accession].get("score") or 0) < _CURE_SCORE
    ]
    client = make_client(1)
    rebuilt: dict[str, dict] = {}
    for accession in rebuild:
        item = next((adj[accession] for adj in adjudications if accession in adj), {})
        filename = item.get("file_used") or item.get("file")
        cik = str(int(item["ciks"][0]))
        raw = _fetch_document(client, cik, accession, filename)
        if raw is None:
            rebuilt[accession] = {"status": "fetch_failed", "file": filename}
            continue
        era = next(
            round_["era"]
            for round_, adj in zip(specimens["rounds"], adjudications)
            if accession in adj
        )
        spec = _round_spec(accession, item, era)
        spec["primary_document"] = filename
        record = _base_record(spec, tree)
        try:
            record, _entries, _timing = extract_filing(
                spec,
                raw,
                f"/Archives/edgar/data/{int(cik)}/"
                f"{accession.replace('-', '')}/{filename}",
                tree=tree,
            )
        except Exception:  # noqa: BLE001 - per-filing isolation is the design
            record["status"] = "error"
            record["error"] = traceback.format_exc(limit=3)
        atomic_write_text(fixtures / f"{accession}.json", json.dumps(record))
        rebuilt[accession] = {
            "status": record.get("status"),
            "file": filename,
            "geometries": len(record.get("geometries") or []),
        }
    match = match_members(
        fixtures,
        _round_targets(specimens, inputs),
        round_accessions,
        _CURE_MIN_CELLS,
    )
    for accession, entry in match.items():
        if entry.get("status") == "matched":
            entry["rebuilt"] = accession in rebuilt
    matched_rows: dict[str, dict] = {}
    for accession in round_accessions:
        entry = match.get(accession) or {}
        if entry.get("status") != "matched":
            continue
        if accession in rebuilt or entry["score"] < _WEAK_SCORE:
            doc = json.loads(
                (fixtures / f"{accession}.json").read_text(encoding="utf-8")
            )
            geometry = next(
                g
                for g in doc.get("geometries") or []
                if g.get("table_index") == entry["table_index"]
            )
            matched_rows[accession] = {
                "table_index": entry["table_index"],
                "score": entry["score"],
                "rows": geometry.get("rows") or [],
            }
    bases = _bases(specimens, match, round_accessions)
    atomic_write_json(out / "bases.json", bases, canonical=False, indent=1)
    atomic_write_json(out / "match-report.json", match, canonical=False, indent=1)
    atomic_write_json(out / "rebuilt.json", rebuilt, canonical=False, indent=1)
    atomic_write_json(
        out / "matched-rows.json", matched_rows, canonical=False, indent=1
    )
    still = {
        a: m
        for a, m in match.items()
        if m.get("status") != "matched" or m["score"] < _WEAK_SCORE
    }
    return {
        "rebuilt": len(rebuilt),
        "matched": sum(1 for m in match.values() if m.get("status") == "matched"),
        "still_weak_or_unmatched": still,
        "bases_members": len(
            bases["members"][specimens["stratum"]][specimens["family"]]
        ),
    }


def rebuild(
    inputs: Path,
    specimens: dict,
    work: Path,
    out: Path,
    *,
    tree: str,
    workers: int | None = None,
) -> dict:
    """Run both stages; report the staging account of record."""
    aggregate = stage_aggregate(
        inputs, specimens, work, out, tree=tree, workers=workers
    )
    prior_match = json.loads((out / "match-report.json").read_text(encoding="utf-8"))
    cure = stage_cure(inputs, specimens, work, out, tree=tree, prior_match=prior_match)
    geometries = 0
    fixtures_dir = work / "fixtures"
    jobs, _round_accessions = specimen_jobs(specimens, inputs)
    for accession, _spec in jobs:
        doc = json.loads(
            (fixtures_dir / f"{accession}.json").read_text(encoding="utf-8")
        )
        geometries += len(doc.get("geometries") or [])
    return {
        "aggregate": aggregate,
        "cure": cure,
        "fixtures_total": aggregate["fixtures_total"],
        "geometries_total": geometries,
    }


def main(argv: list[str] | None = None) -> int:
    """Rebuild adjudicated-specimen fixtures in two stages."""
    parser = argparse.ArgumentParser(prog="fixture_rebuild")
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--specimens", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tree", default="unknown")
    parser.add_argument("--workers", type=int)
    args = parser.parse_args(argv)
    summary = rebuild(
        args.inputs,
        load_specimens(args.specimens),
        args.work,
        args.out,
        tree=args.tree,
        workers=args.workers,
    )
    print(json.dumps(summary, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
