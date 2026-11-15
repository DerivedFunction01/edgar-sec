"""Sampling over the collect's returns (config step).

Grouped-contract sample: per family per stratum, seeded, stratified
across score bands, exactly the Step 4 sample plan; band population
counts ride along. Assembly sample: non-competition families, capped.
"""

from __future__ import annotations

import collections
import hashlib
import json
import sys
from pathlib import Path

from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.tools.measurement.config import BANDS, load_config, workdir

CONFIG = load_config()
HERE = workdir(CONFIG)
SEED = CONFIG["sample_seed"]
GROUPED_CAP = CONFIG["caps"]["grouped"]
BALANCE_SHEET_CAP = CONFIG["caps"]["balance_sheet"]
ASSEMBLY_CAP = CONFIG["caps"]["assembly"]
PREFIX = CONFIG["prefix"]
COMPETITION_FAMILIES = {
    "aoci_rollforward",
    "balance_sheet",
    "cash_flow",
    "comprehensive_income",
    "debt_maturity",
    "deferred_tax",
    "derivatives_hedging",
    "eps_reconciliation",
    "equity_statement",
    "fair_value",
    "income_statement",
    "intangibles",
    "inventory",
    "lease_maturity",
    "pension",
    "ppe",
    "related_party",
    "segment_reporting",
    "stock_comp_rollforward",
    "tax_reconciliation",
}


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def seeded(rows: list[dict], key: str) -> list[dict]:
    return sorted(
        rows, key=lambda r: hashlib.md5(f"{SEED}:{r[key]}".encode()).hexdigest()
    )


def band_of(score: float) -> int:
    for i, (low, high) in enumerate(BANDS):
        if low <= score < high:
            return i
    return len(BANDS) - 1


def main() -> int:
    results_dir = Path(sys.argv[1])
    out_dir = HERE / "samples"
    out_dir.mkdir(exist_ok=True)
    report: dict = {}
    for stratum in ("b", "d"):
        packets = {
            p["specimen_id"]: p
            for p in load_jsonl(results_dir / f"{PREFIX}-packets-{stratum}.jsonl")
        }
        returns = load_jsonl(results_dir / f"{PREFIX}-returns-{stratum}.jsonl")
        by_family: dict[str, list[dict]] = {}
        for r in returns:
            by_family.setdefault(r["family"], []).append(r)
        grouped_sample: list[dict] = []
        band_population: dict[str, dict[str, int]] = {}
        for family, rows in sorted(by_family.items()):
            cap = BALANCE_SHEET_CAP if family == "balance_sheet" else GROUPED_CAP
            ordered = seeded(rows, "specimen_id")
            by_band: dict[int, list[dict]] = {}
            for r in ordered:
                by_band.setdefault(band_of(r["score"]), []).append(r)
            band_population[family] = {
                str(b): len(v) for b, v in sorted(by_band.items())
            }
            picked: list[dict] = []
            band_order = sorted(by_band)
            while len(picked) < min(cap, len(ordered)):
                progressed = False
                for b in band_order:
                    if by_band[b] and len(picked) < cap:
                        picked.append(by_band[b].pop(0))
                        progressed = True
                if not progressed:
                    break
            grouped_sample.extend(picked)
        assignments = load_jsonl(results_dir / f"{PREFIX}-assignments-{stratum}.jsonl")
        asg_by_family: dict[str, list[dict]] = {}
        for a in assignments:
            if a["family"] in COMPETITION_FAMILIES or a["family"] == "other":
                continue
            asg_by_family.setdefault(a["family"], []).append(a)
        assembly_sample: list[dict] = []
        for family, rows in sorted(asg_by_family.items()):
            picked = seeded(rows, "specimen_id")[:ASSEMBLY_CAP]
            assembly_sample.extend(
                {
                    "specimen_id": r["specimen_id"],
                    "family": family,
                    "mechanism": r.get("mechanism"),
                }
                for r in picked
            )
        named_samples: list[tuple[str, list[dict]]] = [
            ("grouped", grouped_sample),
            ("assembly", assembly_sample),
        ]
        if CONFIG.get("aoci_variant"):
            on = load_jsonl(results_dir / f"{PREFIX}-returns-{stratum}-on.jsonl")
            off = load_jsonl(results_dir / f"{PREFIX}-returns-{stratum}-off.jsonl")
            on_keys = {(r["specimen_id"], r["family"]) for r in on}
            differing = [
                r
                for r in off
                if r["family"] == "aoci_rollforward"
                and (r["specimen_id"], r["family"]) not in on_keys
            ]
            named_samples.append(
                ("aoci", seeded(differing, "specimen_id")[: CONFIG["caps"]["aoci"]])
            )
        for name, sample in named_samples:
            with open(out_dir / f"sample-{name}-{stratum}.jsonl", "w") as fh:
                for r in sample:
                    fh.write(
                        json.dumps(
                            {
                                "specimen_id": r["specimen_id"],
                                "family": r["family"],
                                **packets[r["specimen_id"]],
                            }
                        )
                        + "\n"
                    )
            with open(out_dir / f"key-{name}-{stratum}.jsonl", "w") as fh:
                for r in sample:
                    fh.write(
                        json.dumps(
                            {
                                "specimen_id": r["specimen_id"],
                                "family": r["family"],
                                "score": r.get("score"),
                                "state": r.get("state"),
                                "is_top": r.get("is_top"),
                                "mechanism": r.get("mechanism"),
                            }
                        )
                        + "\n"
                    )
        report[stratum] = {
            "returns": len(returns),
            "grouped_sampled": len(grouped_sample),
            "grouped_by_family": dict(
                collections.Counter(r["family"] for r in grouped_sample)
            ),
            "assembly_sampled": len(assembly_sample),
            "assembly_by_family": dict(
                collections.Counter(r["family"] for r in assembly_sample)
            ),
            "band_population": band_population,
        }
        print(stratum, json.dumps(report[stratum]))
    atomic_write_json(
        out_dir / "sample-summary.json", report, canonical=False, indent=1
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
