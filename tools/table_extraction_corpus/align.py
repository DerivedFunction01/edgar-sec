"""Content-align inherited labels for geometry-count-drift filings.

A handful of filings segment cover or prose fragments differently
between the retained corpus's build tree and the current tree, so
their geometry counts differ by a fragment or two and index-based
label attachment would misalign past the drift point. For those
filings only, labels are re-attached by canonical content-stream
match against the retained geometries; unmatched fragments on either
side carry no label and are named in the fixture's builder block.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def _canon(rows: list) -> tuple:
    return tuple("".join("".join(cell.split()) for cell in row) for row in rows)


def align_filing(retained: dict, successor: dict) -> dict:
    """Re-attach one successor fixture's labels by content match."""
    retained_by_canon: dict[str, list[dict]] = {}
    labels = {lab["table_index"]: lab for lab in retained.get("labels", [])}
    for geo in retained.get("geometries", []):
        retained_by_canon.setdefault(_canon(geo["rows"]), []).append(
            labels.get(geo["table_index"])
        )
    matched = 0
    successor_only: list[str] = []
    for geo in successor.get("geometries", []):
        bucket = retained_by_canon.get(_canon(geo["rows"]))
        if bucket:
            geo["label"] = bucket.pop(0)
            matched += 1
        else:
            geo["label"] = None
            successor_only.append(str(geo["rows"][:1])[:120])
    remaining = Counter(
        {canon: len(bucket) for canon, bucket in retained_by_canon.items() if bucket}
    )
    retained_only: list[str] = []
    for geo in retained.get("geometries", []):
        canon = _canon(geo["rows"])
        if remaining.get(canon, 0) > 0:
            retained_only.append(str(geo["rows"][:1])[:120])
            remaining[canon] -= 1
    successor["builder"] = {
        **successor.get("builder", {}),
        "label_alignment": "content-match",
        "alignment_note": (
            f"{matched} geometries content-matched to the retained corpus; "
            f"successor-only fragments: {successor_only}; "
            f"retained-only fragments: {retained_only}; the deltas are "
            "cover/prose-fragment segmentation differences between the "
            "retained corpus's build tree and the current tree"
        ),
    }
    return successor


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--retained", required=True)
    parser.add_argument("--successor", required=True)
    parser.add_argument("--accessions-file", required=True)
    args = parser.parse_args()

    accessions = [
        line.strip()
        for line in Path(args.accessions_file).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for accession in accessions:
        retained = json.loads(
            (Path(args.retained) / f"{accession}.json").read_text(encoding="utf-8")
        )
        target = Path(args.successor) / f"{accession}.json"
        successor = json.loads(target.read_text(encoding="utf-8"))
        target.write_text(
            json.dumps(align_filing(retained, successor)), encoding="utf-8"
        )
        print(f"aligned {accession}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
