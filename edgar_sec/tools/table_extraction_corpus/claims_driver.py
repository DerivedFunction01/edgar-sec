"""Production claims emit/read driver over a staged fixture corpus.

Stages fixture filings, drives the production claim path
(compete_filing over structured geometry texts), emits every
geometry's claims plus a gold log over a bases file's member
sets, and diffs an emit against a gold frame at set level.
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from edgar_sec.engine.tables.ascii_html.model.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.cascade.filing_competition import (
    compete_filing,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    geometry_text_from_table,
)
from edgar_sec.engine.tables.extraction.core.text.context import TableContext
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table
from edgar_sec.foundation.runtime.resources import derive_resources
from edgar_sec.infra.storage.atomic import atomic_write_json, atomic_write_text

ROWS_NAME = "rows.jsonl"
GOLD_NAME = "gold.jsonl"
SUMMARY_NAME = "summary.json"
_PROBE_ROWS_NAME = "int-rows.jsonl"
_PROBE_SUMMARY_NAME = "int-emit-summary.json"

_GOLD: dict[str, list[dict]] = {}  # accession -> [{bare, family}]


def specimen_key(accession: str, table_index, occurrence: int) -> str:
    """A geometry's specimen key: accession:index#occurrence."""
    return f"{accession}:{table_index or 0}#{occurrence}"


def bare_key(specimen: str) -> str:
    """A specimen key without its occurrence ordinal."""
    return specimen.split("#")[0]


def occurrence_ordinals(geometries: list[dict]) -> list[int]:
    """Each geometry's 0-based occurrence ordinal of its index."""
    seen: dict[int, int] = {}
    out: list[int] = []
    for g in geometries:
        idx = g.get("table_index") or 0
        k = seen.get(idx, 0)
        seen[idx] = k + 1
        out.append(k)
    return out


def parse_fxspec(spec: str) -> tuple[str, str]:
    """Split one '<fixtures_dir>:<stratum>' staging spec."""
    path, stratum = spec.rsplit(":", 1)
    return path, stratum


def load_bases(bases_path: str | Path) -> dict:
    """Read a bases file: {'members': {stratum: {family: [rec]}}}."""
    return json.loads(Path(bases_path).read_text())


def member_keys(bases: dict) -> dict[str, set[str]]:
    """Member specimen keys per family, across every stratum."""
    out: dict[str, set[str]] = {}
    for by_family in (bases.get("members") or {}).values():
        for family, records in by_family.items():
            out.setdefault(family, set()).update(
                rec["specimen_id"] for rec in records or []
            )
    return out


def _load_gold(bases: dict) -> None:
    _GOLD.clear()
    for by_family in (bases.get("members") or {}).values():
        for family, records in by_family.items():
            for rec in records or []:
                bare = rec["specimen_id"]
                accession = bare.rsplit(":", 1)[0]
                _GOLD.setdefault(accession, []).append({"bare": bare, "family": family})


def _context(record: dict) -> TableContext:
    grid = ResolvedGrid(
        rows=tuple(tuple(str(c) for c in row) for row in record.get("rows") or ()),
        column_alignments=(),
        column_widths=(),
        header_row_count=record.get("header_row_count") or 0,
    )
    geometry = TableGeometry(
        table_index=record.get("table_index") or 0,
        render_result=TableRenderResult(
            ascii_text="",
            resolved_grid=grid,
            confidence=record.get("confidence", 1.0),
        ),
    )
    return TableContext.from_record(geometry, record)


def _texts(doc: dict):
    geoms = sorted(doc.get("geometries") or [], key=lambda g: g.get("table_index") or 0)
    texts = [geometry_text_from_table(structure_table(_context(g))) for g in geoms]
    return geoms, texts


def _emit_one(arg):
    path, stratum = arg
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    accession = doc["accession"]
    geoms, texts = _texts(doc)
    results = compete_filing(texts)
    ordinals = occurrence_ordinals(geoms)
    gold_rows: dict[str, list[dict]] = {}
    for r in _GOLD.get(accession, []):
        gold_rows.setdefault(r["bare"], []).append(r)
    rows: list[dict] = []
    logs: list[dict] = []
    for gi, (g, result) in enumerate(zip(geoms, results)):
        specimen = specimen_key(accession, g.get("table_index"), ordinals[gi])
        bare = f"{accession}:{g.get('table_index')}"
        rows.append(
            {
                "specimen": specimen,
                "accession": accession,
                "stratum": stratum,
                "claims": list(result.claims),
            }
        )
        for grow in gold_rows.get(bare, []):
            family = grow["family"]
            score = result.scores.get(family)
            logs.append(
                {
                    "specimen": specimen,
                    "bare": bare,
                    "stratum": stratum,
                    "family": family,
                    "entered": family in result.scores,
                    "score": None if score is None else round(score.total, 3),
                    "seated": family in result.claims,
                    "claims": list(result.claims),
                }
            )
    return rows, logs


def _filings(fixtures_dirs) -> list[tuple[str, str]]:
    out = []
    for d, stratum in fixtures_dirs:
        for p in sorted(Path(d).glob("*.json")):
            out.append((str(p), stratum))
    return out


def emit_claims(
    fixtures_dirs: list[tuple[str, str]],
    bases_path: str | Path,
    out_dir: str | Path,
    workers: int | None = None,
) -> dict:
    """Emit claims over the staged corpus; write rows/gold/summary."""
    _load_gold(load_bases(bases_path))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = _filings(fixtures_dirs)
    resolved = workers if workers and workers > 0 else derive_resources().workers
    all_rows: list[dict] = []
    all_logs: list[dict] = []
    if resolved > 1 and len(files) > 1:
        with ProcessPoolExecutor(max_workers=resolved) as pool:
            for rows, logs in pool.map(_emit_one, files, chunksize=8):
                all_rows.extend(rows)
                all_logs.extend(logs)
    else:
        for arg in files:
            rows, logs = _emit_one(arg)
            all_rows.extend(rows)
            all_logs.extend(logs)
    atomic_write_text(out / ROWS_NAME, "".join(json.dumps(r) + "\n" for r in all_rows))
    atomic_write_text(out / GOLD_NAME, "".join(json.dumps(r) + "\n" for r in all_logs))
    family_claims: dict[str, int] = {}
    for r in all_rows:
        for family in r["claims"]:
            family_claims[family] = family_claims.get(family, 0) + 1
    summary = {
        "filings": len(files),
        "geometries": len(all_rows),
        "gold_rows": len(all_logs),
        "family_claims": dict(sorted(family_claims.items())),
    }
    atomic_write_json(out / SUMMARY_NAME, summary, canonical=False, indent=1)
    return summary


def load_rows(rows_path: str | Path) -> list[dict]:
    """Read an emit rows file (one JSON object per line)."""
    return [
        json.loads(ln) for ln in Path(rows_path).read_text().splitlines() if ln.strip()
    ]


def claim_sets(rows: list[dict]) -> dict[str, set[str]]:
    """Bare specimen keys claiming each family, per family."""
    out: dict[str, set[str]] = {}
    for r in rows:
        for family in r.get("claims") or []:
            out.setdefault(family, set()).add(bare_key(r["specimen"]))
    return out


def _find(directory: Path, finished: str, probe: str) -> Path:
    candidate = directory / finished
    return candidate if candidate.exists() else directory / probe


def _summary_family_claims(summary: dict) -> dict[str, int]:
    if "family_claims" in summary:
        return dict(summary["family_claims"])
    return {
        k[: -len("_claims")]: v
        for k, v in summary.items()
        if k.endswith("_claims") and isinstance(v, int)
    }


def diff_emit_dirs(
    emit_dir: str | Path,
    gold_dir: str | Path,
    bases_path: str | Path | None = None,
) -> dict:
    """Diff an emit against a gold frame at set level."""
    emit_dir, gold_dir = Path(emit_dir), Path(gold_dir)
    emit_rows = load_rows(_find(emit_dir, ROWS_NAME, _PROBE_ROWS_NAME))
    gold_rows = load_rows(_find(gold_dir, ROWS_NAME, _PROBE_ROWS_NAME))
    emit_sets, gold_sets = claim_sets(emit_rows), claim_sets(gold_rows)
    families: dict[str, dict] = {}
    equal = True
    for family in sorted(set(emit_sets) | set(gold_sets)):
        e, g = emit_sets.get(family, set()), gold_sets.get(family, set())
        families[family] = {
            "emit_keys": len(e),
            "gold_keys": len(g),
            "only_emit": sorted(e - g),
            "only_gold": sorted(g - e),
        }
        equal = equal and e == g
    verdict: dict = {"equal": equal, "families": families}
    emit_summary = json.loads(
        _find(emit_dir, SUMMARY_NAME, _PROBE_SUMMARY_NAME).read_text()
    )
    gold_summary = json.loads(
        _find(gold_dir, SUMMARY_NAME, _PROBE_SUMMARY_NAME).read_text()
    )
    counts: dict[str, list] = {}
    for field in ("filings", "geometries", "gold_rows"):
        if field in emit_summary and field in gold_summary:
            counts[field] = [emit_summary[field], gold_summary[field]]
            equal = equal and emit_summary[field] == gold_summary[field]
    e_fam = _summary_family_claims(emit_summary)
    g_fam = _summary_family_claims(gold_summary)
    for family in sorted(set(e_fam) | set(g_fam)):
        counts[f"family_claims:{family}"] = [e_fam.get(family), g_fam.get(family)]
        equal = equal and e_fam.get(family) == g_fam.get(family)
    verdict["counts"] = counts
    if bases_path is not None:
        members = member_keys(load_bases(bases_path))
        member_view: dict[str, dict] = {}
        for family in sorted(members):
            e = emit_sets.get(family, set()) & members[family]
            g = gold_sets.get(family, set()) & members[family]
            member_view[family] = {
                "emit_member_claims": len(e),
                "gold_member_claims": len(g),
                "only_emit": sorted(e - g),
                "only_gold": sorted(g - e),
            }
            equal = equal and e == g
        verdict["members"] = member_view
    verdict["equal"] = equal
    return verdict


def main(argv: list[str] | None = None) -> int:
    """Stage, emit, and diff production claims over a fixture corpus."""
    parser = argparse.ArgumentParser(prog="claims_driver")
    sub = parser.add_subparsers(dest="command", required=True)
    emit = sub.add_parser("emit")
    emit.add_argument("bases", type=Path)
    emit.add_argument("out_dir", type=Path)
    emit.add_argument("fxspecs", nargs="+")
    diff = sub.add_parser("diff")
    diff.add_argument("emit_dir", type=Path)
    diff.add_argument("gold_dir", type=Path)
    diff.add_argument("--bases", type=Path)
    args = parser.parse_args(argv)
    if args.command == "emit":
        summary = emit_claims(
            [parse_fxspec(s) for s in args.fxspecs], args.bases, args.out_dir
        )
        print(json.dumps(summary, indent=1, sort_keys=True))
        return 0
    verdict = diff_emit_dirs(args.emit_dir, args.gold_dir, args.bases)
    print(json.dumps(verdict, indent=1, sort_keys=True))
    return 0 if verdict["equal"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
