"""Merge slice verdicts; verify set equality against the packets.

Claim verdicts are keyed (specimen_id, family); sweep verdicts by
specimen_id. Writes verdicts-final/{grouped,assembly,sweep}-{b,d}.jsonl
in scorer input shape. Any missing/extra/duplicate aborts the merge.
"""

import json
import sys
from pathlib import Path

from edgar_sec.tools.measurement.config import load_config, workdir

CONFIG = load_config()
HERE = workdir(CONFIG)


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def main() -> int:
    verdicts_dir = HERE / "verdicts"
    out = HERE / "verdicts-final"
    out.mkdir(exist_ok=True)
    packets: dict[tuple, dict] = {}
    for f in sorted((HERE / "slices").glob("claim-slice-*.jsonl")):
        for row in load(f):
            packets[(row["specimen_id"], row["family"])] = row
    verdicts: dict[tuple, dict] = {}
    dupes = []
    for f in sorted(verdicts_dir.glob("claim-slice-*.jsonl")):
        for row in load(f):
            key = (row["specimen_id"], row["family"])
            if key in verdicts:
                dupes.append(key)
            verdicts[key] = row
    missing = set(packets) - set(verdicts)
    extra = set(verdicts) - set(packets)
    print(
        "claim packets",
        len(packets),
        "verdicts",
        len(verdicts),
        "missing",
        len(missing),
        "extra",
        len(extra),
        "dupes",
        len(dupes),
    )
    assert not missing and not extra and not dupes, (missing, extra, dupes)
    counts: dict[str, int] = {}
    for key, packet in packets.items():
        v = verdicts[key]
        row = {
            "specimen_id": key[0],
            "family": key[1],
            "verdict": v["verdict"],
            "true_family": v.get("true_family"),
            "false_claim_true_class": v.get("false_claim_true_class"),
            "false_claim_mechanism": v.get("false_claim_mechanism"),
        }
        name = f"{packet['_kind']}-{packet['_stratum']}"
        counts[name] = counts.get(name, 0) + 1
        with open(out / f"{name}.jsonl", "a") as fh:
            fh.write(json.dumps(row) + "\n")
    print("claim written", counts)
    sweep_packets: dict[str, dict] = {}
    for f in sorted((HERE / "slices").glob("sweep-slice-*.jsonl")):
        for row in load(f):
            sweep_packets[row["specimen_id"]] = row
    sweep_verdicts: dict[str, dict] = {}
    sdupes = []
    for f in sorted(verdicts_dir.glob("sweep-slice-*.jsonl")):
        for row in load(f):
            if row["specimen_id"] in sweep_verdicts:
                sdupes.append(row["specimen_id"])
            sweep_verdicts[row["specimen_id"]] = row
    smissing = set(sweep_packets) - set(sweep_verdicts)
    sextra = set(sweep_verdicts) - set(sweep_packets)
    print(
        "sweep packets",
        len(sweep_packets),
        "verdicts",
        len(sweep_verdicts),
        "missing",
        len(smissing),
        "extra",
        len(sextra),
        "dupes",
        len(sdupes),
    )
    assert not smissing and not sextra and not sdupes, (smissing, sextra, sdupes)
    scounts: dict[str, int] = {}
    for sid, packet in sweep_packets.items():
        v = sweep_verdicts[sid]
        row = {
            "specimen_id": sid,
            "true_family": v["true_family"],
            "second_family": v.get("second_family"),
            "genre_class": v.get("genre_class"),
        }
        name = f"sweep-{packet['_stratum']}"
        scounts[name] = scounts.get(name, 0) + 1
        with open(out / f"{name}.jsonl", "a") as fh:
            fh.write(json.dumps(row) + "\n")
    print("sweep written", scounts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
