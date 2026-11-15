"""Re-read scoring: verdict flips and class agreement per stratum."""

import json
from pathlib import Path

from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.tools.measurement.config import load_config, workdir

CONFIG = load_config()
HERE = workdir(CONFIG)

key = {}
for line in (HERE / "reread-key.jsonl").read_text().splitlines():
    row = json.loads(line)
    key[row["blind_id"]] = row

second = {}
for i in range(3):
    p = HERE / "verdicts-reread" / f"reread-slice-{i}.jsonl"
    if not p.exists():
        continue
    for line in p.read_text().splitlines():
        row = json.loads(line)
        second[row["specimen_id"]] = row

print("key", len(key), "second", len(second))
out = {}
for stratum in ("b", "d"):
    rows = [k for k in key.values() if k["stratum"] == stratum]
    flips = 0
    compared = 0
    class_compared = 0
    class_agree = 0
    for k in rows:
        s = second.get(k["blind_id"])
        if s is None:
            continue
        compared += 1
        if s["verdict"] != k["first_verdict"]:
            flips += 1
        elif k["first_verdict"] == "not-member" or (
            s.get("true_family") and s["true_family"] != k["family"]
        ):
            class_compared += 1
            if s.get("false_claim_true_class") == k["first_true_class"]:
                class_agree += 1
    out[stratum.upper()] = {
        "n": len(rows),
        "compared": compared,
        "flips": flips,
        "flip_rate": round(flips / compared, 4) if compared else None,
        "class_compared": class_compared,
        "class_agreement": round(class_agree / class_compared, 4)
        if class_compared
        else None,
    }
atomic_write_json(HERE / "reread-results.json", out, canonical=False, indent=1)
print(json.dumps(out, indent=1))
