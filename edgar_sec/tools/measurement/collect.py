"""Collect: the landed hand over fresh fixtures (config step).

Per filing, two instruments over the same geometries: compete_filing
grouped returns and assembly assignments with a direct toc_refusal
read per table, plus a seeded uniform sweep sample per stratum.
"""

from __future__ import annotations

from edgar_sec.tools.measurement.config import load_config

import collections
import hashlib
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from edgar_sec.domain.forms.families.annual.location import section_scopes
from edgar_sec.engine.tables.ascii_html.model.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.assembly.assembly import assemble
from edgar_sec.engine.tables.extraction.core.text.context import TableContext
from edgar_sec.engine.tables.extraction.cascade.filing_competition import compete_filing
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
    geometry_text_from_table,
)
from edgar_sec.engine.tables.extraction.seats.toc_gate import toc_refusal
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table
from edgar_sec.foundation.runtime.resources import derive_resources
from edgar_sec.infra.storage.atomic import atomic_write_json

TEXT_CAP = 6000
SWEEP_N = 700
CONFIG = load_config()
SWEEP_SEED = CONFIG["sweep_seed"]
PREFIX = CONFIG["prefix"]


def geometry_text(g: dict) -> GeometryText:
    """One fixture geometry's channel text, mirroring the TypedTable seam."""
    return geometry_text_from_table(structure_table(_context(g)))


def packet(accession: str, g: dict) -> dict:
    """The adjudication packet for one geometry: text only, no claims."""
    rows = g.get("rows") or []
    table_text = "\n".join(" | ".join(str(c) for c in row) for row in rows)
    return {
        "specimen_id": f"{accession}:{g.get('table_index')}",
        "accession": accession,
        "table_index": g.get("table_index"),
        "caption_stack": g.get("caption_stack") or [],
        "prose_before": (g.get("prose_before") or "")[-TEXT_CAP:],
        "prose_after": (g.get("prose_after") or "")[:2000],
        "table_text": table_text[:TEXT_CAP],
        "structured_location": g.get("structured_location"),
    }


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


def run_filing(path: Path) -> tuple[list, list, list, list, dict]:
    """Returns, assignments, toc reads and packets for one fixture."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    accession = doc["accession"]
    geoms = sorted(doc.get("geometries") or [], key=lambda g: g.get("table_index") or 0)
    texts = [geometry_text(g) for g in geoms]
    results = compete_filing(texts, scopes=section_scopes())
    returns: list[dict] = []
    packets: dict[str, dict] = {}
    for g, result in zip(geoms, results):
        if not result.groups:
            continue
        specimen = f"{accession}:{g.get('table_index')}"
        top = max(result.groups, key=lambda gr: gr.score)
        for gr in result.groups:
            returns.append(
                {
                    "specimen_id": specimen,
                    "family": gr.family,
                    "score": gr.score,
                    "state": gr.state,
                    "role": gr.role,
                    "is_top": gr.family == top.family,
                    "claims": list(result.claims),
                    "contested": list(result.contested),
                }
            )
        packets[specimen] = packet(accession, g)
    contexts = [_context(g) for g in geoms]
    assembly = assemble(contexts)
    assignments: list[dict] = []
    for a in assembly.assignments:
        specimen = f"{accession}:{a.table_index}"
        assignments.append(
            {"specimen_id": specimen, "family": a.family, "mechanism": a.mechanism}
        )
        if specimen not in packets:
            g = next(x for x in geoms if (x.get("table_index") or 0) == a.table_index)
            packets[specimen] = packet(accession, g)
    toc: list[dict] = []
    for context in contexts:
        table = structure_table(context)
        specimen = f"{accession}:{context.geometry.table_index}"
        toc.append(
            {"specimen_id": specimen, "toc_refused": toc_refusal(table) is not None}
        )
    all_ids = [f"{accession}:{g.get('table_index')}" for g in geoms]
    counts = {
        "geometries": len(geoms),
        "return_families": dict(collections.Counter(r["family"] for r in returns)),
        "assignment_families": dict(
            collections.Counter(a["family"] for a in assignments)
        ),
        "toc_refused": sum(1 for t in toc if t["toc_refused"]),
    }
    return (
        returns,
        assignments,
        toc,
        list(packets.values()),
        {
            "all_ids": all_ids,
            "counts": counts,
            "packets_by_id": packets,
        },
    )


def main() -> int:
    fixtures_dir, stratum, out_dir = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    out_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(fixtures_dir.glob("*.json"))
    all_returns: list[dict] = []
    all_assignments: list[dict] = []
    all_toc: list[dict] = []
    union_packets: dict[str, dict] = {}
    all_packets: dict[str, dict] = {}
    totals: dict = {"geometries": 0, "toc_refused": 0}
    ret_tot: collections.Counter = collections.Counter()
    asg_tot: collections.Counter = collections.Counter()
    with ProcessPoolExecutor(max_workers=derive_resources().workers) as pool:
        for returns, assignments, toc, packets, extra in pool.map(
            run_filing, files, chunksize=4
        ):
            all_returns.extend(returns)
            all_assignments.extend(assignments)
            all_toc.extend(toc)
            for p in packets:
                union_packets[p["specimen_id"]] = p
            all_packets.update(extra["packets_by_id"])
            totals["geometries"] += extra["counts"]["geometries"]
            totals["toc_refused"] += extra["counts"]["toc_refused"]
            ret_tot.update(extra["counts"]["return_families"])
            asg_tot.update(extra["counts"]["assignment_families"])
    # The sweep needs packets for unclaimed geometries too; rebuild
    # them from the fixture files for the seeded sweep ids only.
    sweep_ids = sorted(
        all_packets.keys() | {t["specimen_id"] for t in all_toc},
        key=lambda s: hashlib.md5(f"{SWEEP_SEED}:{s}".encode()).hexdigest(),
    )[:SWEEP_N]
    # all_packets only holds claimed/assigned packets; unclaimed
    # sweep packets are rebuilt below from fixtures.
    sweep_set = set(sweep_ids)
    missing = sweep_set - set(all_packets)
    if missing:
        by_accession: dict[str, set[int]] = collections.defaultdict(set)
        for sid in missing:
            acc, idx = sid.rsplit(":", 1)
            by_accession[acc].add(int(idx))
        for path in files:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if doc["accession"] not in by_accession:
                continue
            for g in doc.get("geometries") or []:
                if (g.get("table_index") or 0) in by_accession[doc["accession"]]:
                    all_packets[f"{doc['accession']}:{g.get('table_index')}"] = packet(
                        doc["accession"], g
                    )
    ret_by_spec: dict[str, list[str]] = collections.defaultdict(list)
    for r in all_returns:
        ret_by_spec[r["specimen_id"]].append(r["family"])
    asg_by_spec = {a["specimen_id"]: a["family"] for a in all_assignments}
    with open(out_dir / f"{PREFIX}-sweep-{stratum}.jsonl", "w") as fh:
        for sid in sweep_ids:
            fh.write(json.dumps(all_packets[sid]) + "\n")
    with open(out_dir / f"{PREFIX}-sweep-key-{stratum}.jsonl", "w") as fh:
        for sid in sweep_ids:
            fh.write(
                json.dumps(
                    {
                        "specimen_id": sid,
                        "return_families": sorted(set(ret_by_spec.get(sid, []))),
                        "assembly_family": asg_by_spec.get(sid),
                    }
                )
                + "\n"
            )
    for name, rows in (
        ("returns", all_returns),
        ("assignments", all_assignments),
        ("toc", all_toc),
    ):
        with open(out_dir / f"{PREFIX}-{name}-{stratum}.jsonl", "w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
    with open(out_dir / f"{PREFIX}-packets-{stratum}.jsonl", "w") as fh:
        for p in union_packets.values():
            fh.write(json.dumps(p) + "\n")
    summary = {
        "stratum": stratum,
        "filings": len(files),
        "geometries": totals["geometries"],
        "toc_refused": totals["toc_refused"],
        "returns": len(all_returns),
        "assignments": len(all_assignments),
        "packets": len(union_packets),
        "sweep": len(sweep_ids),
        "return_families": dict(ret_tot),
        "assignment_families": dict(asg_tot),
    }
    atomic_write_json(
        out_dir / f"{PREFIX}-collect-summary-{stratum}.json",
        summary,
        canonical=False,
        indent=1,
    )
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
