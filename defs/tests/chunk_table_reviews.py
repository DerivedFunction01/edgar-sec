"""Split a review manifest into deterministic fixed-size review batches."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--size", type=int, default=20)
    args = parser.parse_args(argv)
    if args.limit <= 0 or args.size <= 0:
        parser.error("--limit and --size must be positive")

    entries = [
        json.loads(line)
        for line in args.manifest.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ][: args.limit]
    if not entries:
        parser.error("manifest contains no entries")

    args.output.mkdir(parents=True, exist_ok=True)
    batches = []
    for start in range(0, len(entries), args.size):
        batch = entries[start : start + args.size]
        number = start // args.size + 1
        path = args.output / f"batch-{number:03d}.jsonl"
        path.write_text(
            "".join(json.dumps(entry, sort_keys=True) + "\n" for entry in batch),
            encoding="utf-8",
        )
        batches.append(
            {
                "batch": number,
                "path": path.name,
                "count": len(batch),
                "table_ids": [entry["table_id"] for entry in batch],
            }
        )
    (args.output / "batches.json").write_text(
        json.dumps(batches, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Wrote {len(batches)} batches covering {len(entries)} tables to {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
