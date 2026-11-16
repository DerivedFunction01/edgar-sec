"""Scoring: verdicts + keys through the protocol machinery.

Per stratum, never blended: grouped precision, top-member rates,
calibration, false-claim classes, band-weighted population precision;
assembly precision; labelled recall; baseline deltas.
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.tools.measurement.config import BANDS, load_config, workdir


from edgar_sec.engine.tables.extraction.measurement import (  # noqa: E402
    AdjudicationRecord,
    GroupReturn,
    calibration_rows,
    false_claim_classes,
    precision_rates,
    top_member_rates,
    unclassified_remainder,
)

CONFIG = load_config()
HERE = workdir(CONFIG)
PREFIX = CONFIG["prefix"]
STRATUM = {"b": "B", "d": "D"}
EXTRA_FAMILIES = ("commitments_contingencies", "subsequent_events")


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def to_record(v: dict, stratum: str) -> AdjudicationRecord:
    return AdjudicationRecord(
        specimen_id=v["specimen_id"],
        stratum=stratum,
        claimed_family=v["family"],
        verdict=v["verdict"],
        true_family=v.get("true_family"),
        false_claim_true_class=v.get("false_claim_true_class"),
        false_claim_mechanism=v.get("false_claim_mechanism"),
    )


def rate_dict(r) -> dict:
    return {
        "estimator": r.estimator,
        "stratum": r.stratum,
        "family": r.family,
        "value": None if r.value is None else round(r.value, 4),
        "n": r.n,
    }


def band_of(score: float) -> int:
    for i, (low, high) in enumerate(BANDS):
        if low <= score < high:
            return i
    return len(BANDS) - 1


def main() -> int:
    results_dir = Path(sys.argv[1])
    verdicts_dir = Path(sys.argv[2])
    out: dict = {"strata": {}}
    all_records: list[AdjudicationRecord] = []
    problems: list[str] = []
    vocab_notes: list[str] = []
    recall_out: dict[str, dict] = {}
    for stratum_key, stratum in STRATUM.items():
        keys = {
            (k["specimen_id"], k["family"]): k
            for k in load_jsonl(HERE / f"samples/key-grouped-{stratum_key}.jsonl")
        }
        verdicts = load_jsonl(verdicts_dir / f"grouped-{stratum_key}.jsonl")
        records = [to_record(v, stratum) for v in verdicts]
        all_records.extend(records)
        for r in records:
            for p in r.problems():
                # The baseline vocabulary predates the
                # subsequent_events family; its gold class is
                # legal current vocabulary, reported separately.
                if "subsequent_events" in p:
                    vocab_notes.append(f"{r.specimen_id}: {p}")
                else:
                    problems.append(f"{r.specimen_id}: {p}")
        returns = tuple(
            GroupReturn(
                specimen_id=k["specimen_id"],
                stratum=stratum,
                family=k["family"],
                score=k["score"],
                state=k["state"],
                is_top=bool(k["is_top"]),
            )
            for k in keys.values()
        )
        by_family: dict[str, list[AdjudicationRecord]] = {}
        for r in records:
            by_family.setdefault(r.claimed_family, []).append(r)
        summary = json.loads((HERE / "samples/sample-summary.json").read_text())
        band_population = summary[stratum_key]["band_population"]
        rec_by_key = {(r.specimen_id, r.claimed_family): r for r in records}
        weighted: dict[str, dict] = {}
        for fam, rs in sorted(by_family.items()):
            pop = band_population.get(fam, {})
            total_pop = sum(pop.values())
            est = {"strict": None, "form_present": None, "population_claims": total_pop}
            band_records: dict[int, list[AdjudicationRecord]] = collections.defaultdict(
                list
            )
            for (sid, f), k in keys.items():
                if f == fam and (sid, f) in rec_by_key:
                    band_records[band_of(k["score"])].append(rec_by_key[(sid, f)])
            for label, pred in (
                ("strict", lambda r: r.is_member),
                ("form_present", lambda r: r.is_member or r.verdict == "split-group"),
            ):
                num = 0.0
                covered = 0
                for b in range(len(BANDS)):
                    band_rs = band_records.get(b, [])
                    pop_b = pop.get(str(b), 0)
                    if band_rs and pop_b:
                        num += pop_b * (
                            sum(1 for r in band_rs if pred(r)) / len(band_rs)
                        )
                        covered += pop_b
                est[label] = round(num / covered, 4) if covered else None
                est[f"{label}_covered_population"] = covered
            weighted[fam] = est
        # assembly (residue/note-tier) precision
        asg_verdicts = load_jsonl(verdicts_dir / f"assembly-{stratum_key}.jsonl")
        asg_precision: dict[str, dict] = {}
        for v in asg_verdicts:
            fam = v["family"]
            slot = asg_precision.setdefault(fam, {"n": 0, "member": 0, "split": 0})
            slot["n"] += 1
            if v["verdict"] == "member" and not (
                v.get("true_family") and v["true_family"] != fam
            ):
                slot["member"] += 1
            if v["verdict"] == "split-group":
                slot["split"] += 1
        for fam, slot in asg_precision.items():
            slot["precision_strict"] = (
                round(slot["member"] / slot["n"], 4) if slot["n"] else None
            )
        # recall: sweep members + grouped cross-reads
        all_returns = load_jsonl(results_dir / f"{PREFIX}-returns-{stratum_key}.jsonl")
        ret_by_spec: dict[str, set[str]] = collections.defaultdict(set)
        for r in all_returns:
            ret_by_spec[r["specimen_id"]].add(r["family"])
        assignments = {
            a["specimen_id"]: a["family"]
            for a in load_jsonl(
                results_dir / f"{PREFIX}-assignments-{stratum_key}.jsonl"
            )
        }

        def claimed(specimen: str, family: str) -> bool:
            return family in ret_by_spec.get(specimen, set()) or (
                assignments.get(specimen) == family
            )

        members: dict[str, list[tuple[str, bool, str]]] = collections.defaultdict(list)
        sweep = load_jsonl(verdicts_dir / f"sweep-{stratum_key}.jsonl")
        for v in sweep:
            fam = v["true_family"]
            if fam in ("none", None):
                continue
            members[fam].append(
                (v["specimen_id"], claimed(v["specimen_id"], fam), "sweep")
            )
            if v.get("second_family"):
                fam2 = v["second_family"]
                members[fam2].append(
                    (v["specimen_id"], claimed(v["specimen_id"], fam2), "sweep2")
                )
        seen = {(f, s) for f, rows in members.items() for s, _, _ in rows}
        for v in verdicts + asg_verdicts:
            fam = v.get("true_family")
            if fam and (fam, v["specimen_id"]) not in seen:
                members[fam].append(
                    (v["specimen_id"], claimed(v["specimen_id"], fam), "cross")
                )
                seen.add((fam, v["specimen_id"]))
        recall: dict[str, dict] = {}
        for fam, rows in sorted(members.items()):
            n = len(rows)
            hits = sum(1 for _, c, _ in rows if c)
            recall[fam] = {
                "recall": round(hits / n, 4) if n else None,
                "n": n,
                "claimed": hits,
                "sweep_n": sum(1 for *_, src in rows if src.startswith("sweep")),
                "cross_n": sum(1 for *_, src in rows if src == "cross"),
            }
        recall_out[stratum] = recall
        out["strata"][stratum] = {
            "precision_by_family": {
                fam: [rate_dict(r) for r in precision_rates(tuple(rs))]
                for fam, rs in sorted(by_family.items())
            },
            "weighted_population_precision": weighted,
            "grouped_top_member": [
                rate_dict(r) for r in top_member_rates(returns, tuple(records))
            ],
            "calibration": [
                rate_dict(r) for r in calibration_rows(returns, tuple(records))
            ],
            "assembly_precision": asg_precision,
            "recall": recall,
            "false_classes_by_family": {
                fam: false_claim_classes(tuple(records), fam)
                for fam in sorted(by_family)
            },
        }
    out["unclassified_remainder"] = {
        s: rate_dict(r) for s, r in unclassified_remainder(tuple(all_records)).items()
    }
    # false-claim class totals across families, per stratum
    totals: dict[str, collections.Counter] = {
        "B": collections.Counter(),
        "D": collections.Counter(),
    }
    for r in all_records:
        if r.is_false_claim:
            totals[r.stratum][r.false_claim_true_class] += 1
    out["false_claim_class_totals"] = {s: dict(c) for s, c in totals.items()}
    # Baseline deltas: the recorded baseline against this run.
    baseline = json.loads(Path(CONFIG["baseline_results"]).expanduser().read_text())
    deltas: dict[str, dict] = {}
    for stratum in ("B", "D"):
        deltas[stratum] = {}
        base_precision = baseline[stratum]["precision_by_family"]
        run_precision = out["strata"][stratum]["precision_by_family"]
        base_top = {
            r["family"]: r["value"] for r in baseline[stratum]["grouped_top_member"]
        }
        run_top = {
            r["family"]: r["value"]
            for r in out["strata"][stratum]["grouped_top_member"]
        }
        for fam in sorted(set(base_precision) | set(run_precision)):
            p_base = next(
                (
                    r["value"]
                    for r in base_precision.get(fam, [])
                    if r["estimator"] == "precision-strict"
                ),
                None,
            )
            p_run = next(
                (
                    r["value"]
                    for r in run_precision.get(fam, [])
                    if r["estimator"] == "precision-strict"
                ),
                None,
            )
            deltas[stratum][fam] = {
                "precision_strict_baseline": p_base,
                "precision_strict_current": p_run,
                "delta_precision": (
                    round(p_run - p_base, 4)
                    if p_base is not None and p_run is not None
                    else None
                ),
                "top_member_baseline": base_top.get(fam),
                "top_member_current": run_top.get(fam),
                "delta_top_member": (
                    round(run_top[fam] - base_top[fam], 4)
                    if fam in base_top
                    and fam in run_top
                    and base_top[fam] is not None
                    and run_top[fam] is not None
                    else None
                ),
            }
    out["delta_vs_baseline"] = deltas
    out["record_problems"] = problems
    out["vocabulary_notes"] = vocab_notes
    out["records_total"] = len(all_records)
    atomic_write_json(HERE / "pricing-results.json", out, canonical=False, indent=1)
    print(
        json.dumps({"records": len(all_records), "problems": problems[:10]}, indent=1)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
