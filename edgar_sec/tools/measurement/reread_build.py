"""Blind re-read: seeded 25% subsample of claim packets under
blind IDs, opened after the first pass is recorded (protocol)."""

import hashlib
import json
from pathlib import Path

from edgar_sec.tools.measurement.config import load_config, workdir

CONFIG = load_config()
HERE = workdir(CONFIG)
SEED = CONFIG["reread_seed"]

packets = {}
for slice_file in sorted((HERE / "slices").glob("claim-slice-*.jsonl")):
    for line in slice_file.read_text().splitlines():
        row = json.loads(line)
        packets[(row["specimen_id"], row["family"])] = row

first = {}
for name in ("grouped-b", "grouped-d", "assembly-b", "assembly-d"):
    p = HERE / "verdicts-final" / f"{name}.jsonl"
    if not p.exists():
        continue
    for line in p.read_text().splitlines():
        row = json.loads(line)
        first[(row["specimen_id"], row["family"])] = row

keys = sorted(
    packets,
    key=lambda k: hashlib.md5(f"{SEED}:{k[0]}:{k[1]}".encode()).hexdigest(),
)
take = keys[: len(keys) // 4]
print("reread n =", len(take), "of", len(keys))

out_packets, out_key = [], []
for key in take:
    packet = packets[key]
    blind_id = (
        "R" + hashlib.md5(f"blind:{SEED}:{key[0]}:{key[1]}".encode()).hexdigest()[:10]
    )
    out_packets.append(
        {
            "specimen_id": blind_id,
            "family": key[1],
            "caption_stack": packet["caption_stack"],
            "prose_before": packet["prose_before"],
            "prose_after": packet["prose_after"],
            "table_text": packet["table_text"],
            "structured_location": packet["structured_location"],
        }
    )
    out_key.append(
        {
            "blind_id": blind_id,
            "specimen_id": key[0],
            "family": key[1],
            "stratum": packet["_stratum"],
            "kind": packet["_kind"],
            "first_verdict": first[key]["verdict"],
            "first_true_class": first[key]["false_claim_true_class"],
        }
    )

(HERE / "reread-packets.jsonl").write_text(
    "".join(json.dumps(r) + "\n" for r in out_packets)
)
(HERE / "reread-key.jsonl").write_text("".join(json.dumps(r) + "\n" for r in out_key))
for i in range(3):
    part = out_packets[i::3]
    (HERE / f"reread-slice-{i}.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in part)
    )
    print("slice", i, len(part))
