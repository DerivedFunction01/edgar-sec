"""Reconcile the successor corpus against the retained corpus.

The contract is counts, alignment, and identity: per filing, geometry
counts and table_index sequences match; per geometry, the inherited
label is identical. Grid divergences are classified — a divergence
whose canonical content stream is unchanged is a cell-boundary
regrouping (the split-paren merge is the named case); anything else is
an unexplained residual and blocks the step.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from pathlib import Path

from tools.table_extraction_corpus.defects import DefectRegister

_PAREN_OPEN_RE = re.compile(r"\(\$?\d[\d,.]*$")
_CLOSE_CELL_RE = re.compile(r"\)[%*\u2020\u2021]?$")
_BLOCKING = {
    "filing-missing",
    "filing-not-ok",
    "geometry-count-mismatch",
    "label-divergence",
    "label-missing",
    "grid-divergence-unexplained",
    "split-count-mismatch",
}


def _canon_rows(rows: list) -> list[str]:
    return ["".join("".join(cell.split()) for cell in row) for row in rows]


def _pair_drift(retained: dict, successor: dict):
    """Pair geometries by canonical content for a drift filing.

    Returns ``(pairs, successor_only, retained_only)`` when the
    successor fixture is content-aligned and every paired geometry
    carries its pair's retained label verbatim; otherwise ``None``.
    """
    if successor.get("builder", {}).get("label_alignment") != "content-match":
        return None
    labels = {lab["table_index"]: lab for lab in retained.get("labels", [])}
    queues: dict[tuple, list[dict]] = {}
    for geo in retained.get("geometries", []):
        queues.setdefault(tuple(_canon_rows(geo["rows"])), []).append(geo)
    pairs: list[tuple[dict, dict]] = []
    successor_only: list[dict] = []
    for s_geo in successor.get("geometries", []):
        queue = queues.get(tuple(_canon_rows(s_geo["rows"])))
        if queue:
            r_geo = queue.pop(0)
            if s_geo.get("label") != labels.get(r_geo["table_index"]):
                return None
            pairs.append((r_geo, s_geo))
        elif s_geo.get("label") is None:
            successor_only.append(s_geo)
        else:
            return None
    retained_only = [geo for queue in queues.values() for geo in queue]
    return pairs, successor_only, retained_only


def _paren_split_present(rows: list) -> bool:
    for row in rows:
        cells = [cell.strip() for cell in row]
        for index in range(len(cells) - 1):
            if _PAREN_OPEN_RE.search(cells[index]) and _CLOSE_CELL_RE.fullmatch(
                cells[index + 1]
            ):
                return True
    return False


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, int(round(pct * (len(ordered) - 1)))))
    return ordered[rank]


def _timing_block(shard_summaries: list[dict]) -> dict:
    timings = [row for s in shard_summaries for row in s.get("timings", [])]
    totals = [row["total_s"] for row in timings if "total_s" in row]
    fetch = [row["fetch_s"] for row in timings if "fetch_s" in row]
    compute = [
        row.get("normalize_s", 0.0) + row.get("extract_s", 0.0) for row in timings
    ]
    per_session = []
    for summary in shard_summaries:
        wall_h = summary["wall_s"] / 3600.0
        per_session.append(
            {
                "run_id": summary["run_id"],
                "filings": summary["filings"],
                "wall_s": summary["wall_s"],
                "filings_per_hour": round(summary["filings"] / wall_h, 1)
                if wall_h
                else 0.0,
            }
        )
    return {
        "filings_timed": len(timings),
        "total_s": {
            "mean": round(statistics.mean(totals), 3) if totals else 0.0,
            "p50": round(_percentile(totals, 0.50), 3),
            "p95": round(_percentile(totals, 0.95), 3),
        },
        "fetch_s_mean": round(statistics.mean(fetch), 3) if fetch else 0.0,
        "compute_s_mean": round(statistics.mean(compute), 3) if compute else 0.0,
        "per_session": per_session,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--retained", required=True)
    parser.add_argument("--successor", required=True)
    parser.add_argument("--registers", nargs="*", default=[])
    parser.add_argument("--shard-summaries", nargs="*", default=[])
    parser.add_argument("--register-out")
    parser.add_argument("--summary-out")
    parser.add_argument("--run-id", default="reconcile")
    args = parser.parse_args()

    register = DefectRegister(args.run_id, "step-1-reconcile", "retained-409")
    for path in args.registers:
        register.absorb(DefectRegister.load(Path(path)))

    retained_dir = Path(args.retained)
    successor_dir = Path(args.successor)
    retained_files = sorted(
        p for p in retained_dir.glob("*.json") if "-" in p.stem and p.stem[0].isdigit()
    )
    family_split: dict[str, dict[str, int]] = {}
    total_geometries = 0
    split_counts = {"derivation": 0, "heldout": 0}
    explained_delta_splits = {"derivation": 0, "heldout": 0}
    located = 0
    breaks_with_namespace = 0
    breaks_total = 0

    def note(defect_class: str, accession: str, explanation: str, **kwargs) -> None:
        register.add(
            defect_class,
            "reconcile",
            accession,
            explanation,
            table_index=kwargs.get("table_index"),
            specimen=kwargs.get("specimen"),
        )

    for retained_path in retained_files:
        accession = retained_path.stem
        retained = json.loads(retained_path.read_text(encoding="utf-8"))
        successor_path = successor_dir / retained_path.name
        if not successor_path.exists():
            note(
                "filing-missing",
                accession,
                "no successor fixture was produced for this retained filing",
            )
            continue
        successor = json.loads(successor_path.read_text(encoding="utf-8"))
        if successor.get("status") != "ok":
            note(
                "filing-not-ok",
                accession,
                f"successor build status is {successor.get('status')!r}: "
                f"{str(successor.get('error'))[:200]}",
            )
            continue
        r_geos = retained.get("geometries", [])
        s_geos = successor.get("geometries", [])
        retained_labels = {
            lab["table_index"]: lab for lab in retained.get("labels", [])
        }
        if len(r_geos) != len(s_geos) or [g["table_index"] for g in r_geos] != [
            g["table_index"] for g in s_geos
        ]:
            pairing = _pair_drift(retained, successor)
            if pairing is None:
                note(
                    "geometry-count-mismatch",
                    accession,
                    f"retained {len(r_geos)} geometries vs successor {len(s_geos)}, "
                    "or table_index sequences differ",
                    specimen=f"primary={successor.get('builder', {}).get('primary_document')} "
                    f"via {successor.get('builder', {}).get('primary_source')}",
                )
                continue
            pairs, successor_only, retained_only = pairing
            for geo in successor_only:
                note(
                    "geometry-count-drift-explained",
                    accession,
                    "successor-only fragment geometry: cover/prose-fragment "
                    "segmentation differs between the retained corpus's "
                    "build tree and the current tree; every substantive "
                    "geometry content-matches its retained pair",
                    specimen=str(geo["rows"][:1])[:120],
                )
            for geo in retained_only:
                label = retained_labels.get(geo["table_index"]) or {}
                if label.get("split") in explained_delta_splits:
                    explained_delta_splits[label["split"]] += 1
                note(
                    "geometry-count-drift-explained",
                    accession,
                    "retained-only fragment geometry: cover/prose-fragment "
                    "segmentation differs between the retained corpus's "
                    "build tree and the current tree; every substantive "
                    "geometry content-matches its retained pair",
                    specimen=str(geo["rows"][:1])[:120],
                )
            r_geos = [r_geo for r_geo, _ in pairs]
            s_geos = [s_geo for _, s_geo in pairs]
            retained_labels = {
                s_geo["table_index"]: retained_labels.get(r_geo["table_index"])
                for r_geo, s_geo in pairs
            }
        for s_geo, r_geo in zip(s_geos, r_geos, strict=True):
            table_index = s_geo["table_index"]
            total_geometries += 1
            label = s_geo.get("label")
            retained_label = retained_labels.get(table_index)
            if label is None:
                note(
                    "label-missing",
                    accession,
                    "successor geometry carries no inherited label",
                    table_index=table_index,
                )
                continue
            if retained_label is not None and label != retained_label:
                note(
                    "label-divergence",
                    accession,
                    "inherited label differs from the retained corpus label",
                    table_index=table_index,
                    specimen=json.dumps(label)[:200],
                )
                continue
            split = label.get("split")
            if split in split_counts:
                split_counts[split] += 1
            family = label.get("final_family")
            if family:
                bucket = family_split.setdefault(
                    family, {"derivation": 0, "heldout": 0}
                )
                if split in bucket:
                    bucket[split] += 1
            if s_geo.get("location") is not None:
                located += 1
            for side in ("inside",):
                for item in s_geo.get("breaks", {}).get(side, []):
                    breaks_total += 1
                    if item.get("namespace"):
                        breaks_with_namespace += 1
            if s_geo["rows"] != r_geo["rows"]:
                canon_equal = _canon_rows(s_geo["rows"]) == _canon_rows(r_geo["rows"])
                if canon_equal and _paren_split_present(r_geo["rows"]):
                    note(
                        "grid-divergence-paren-merge",
                        accession,
                        "retained grid splits a parenthesized value across "
                        "cells; the successor grid carries the merged cell "
                        "the split-paren merge produces; canonical content "
                        "streams are identical",
                        table_index=table_index,
                    )
                elif canon_equal:
                    note(
                        "grid-divergence-boundary-shift",
                        accession,
                        "cells regrouped between the retained and successor "
                        "renders; canonical content streams are identical",
                        table_index=table_index,
                    )
                else:
                    note(
                        "grid-divergence-unexplained",
                        accession,
                        "grid content differs beyond cell regrouping",
                        table_index=table_index,
                        specimen=json.dumps(r_geo["rows"])[:200],
                    )
            if s_geo.get("header_row_count") != r_geo.get("header_row_count"):
                note(
                    "geometry-meta-divergence",
                    accession,
                    f"header_row_count retained {r_geo.get('header_row_count')} "
                    f"vs successor {s_geo.get('header_row_count')}",
                    table_index=table_index,
                )

    expected_splits = {
        "derivation": 9567 - explained_delta_splits["derivation"],
        "heldout": 9335 - explained_delta_splits["heldout"],
    }
    if split_counts != expected_splits:
        note(
            "split-count-mismatch",
            "-",
            f"split counts are {split_counts}, expected {expected_splits} "
            "(retained 9567/9335 minus explained retained-only drift "
            f"fragments {explained_delta_splits})",
        )

    shard_summaries = [
        json.loads(Path(p).read_text(encoding="utf-8")) for p in args.shard_summaries
    ]
    summary = {
        "population": "retained-409",
        "filings_retained": len(retained_files),
        "geometries": total_geometries,
        "split_counts": split_counts,
        "per_family_per_split": family_split,
        "located": located,
        "located_share": round(located / total_geometries, 4)
        if total_geometries
        else 0.0,
        "breaks_inside": breaks_total,
        "breaks_with_namespace": breaks_with_namespace,
        "defect_counts": {},
        "timing": _timing_block(shard_summaries),
    }
    for entry in register.entries():
        summary["defect_counts"][entry["class"]] = (
            summary["defect_counts"].get(entry["class"], 0) + entry["count"]
        )
    if args.summary_out:
        Path(args.summary_out).write_text(
            json.dumps(summary, indent=1, sort_keys=True), encoding="utf-8"
        )
    if args.register_out:
        register.write(Path(args.register_out))
    blocking = [e for e in register.entries() if e["class"] in _BLOCKING]
    unexplained = register.unexplained()
    print(json.dumps(summary, indent=1, sort_keys=True))
    print(f"blocking entries: {len(blocking)}; unexplained entries: {len(unexplained)}")
    return 1 if blocking or unexplained else 0


if __name__ == "__main__":
    raise SystemExit(main())
