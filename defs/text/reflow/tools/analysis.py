"""Offline inventory and annotation export for reflow prose/layout analysis.

Build an immutable inventory from the existing review corpus without SEC or
model calls::

    python -m defs.text.reflow.tools.analysis inventory \
        --review-root scratch/target_review --inventory-id review-v1

Annotate the generated JSONL template, then export the labeled Parquet set::

    python -m defs.text.reflow.tools.analysis export \
        --inventory-id review-v1 --labelset-id labels-v1 \
        --annotations completed-labels.jsonl
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from defs.runtime.paths import resolve_paths

from .analysis_export import export_labeled_inventory
from .analysis_inventory import build_inventory


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or export an offline reflow analysis inventory"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory = subparsers.add_parser(
        "inventory", help="verify review files and create Parquet inventory"
    )
    inventory.add_argument("--review-root", type=Path, required=True)
    inventory.add_argument("--inventory-id")
    inventory.add_argument("--controls-per-role-per-document", type=int, default=2)
    inventory.add_argument("--block-batch-size", type=int, default=5_000)
    inventory.add_argument("--token-batch-size", type=int, default=50_000)

    export = subparsers.add_parser(
        "export", help="join reviewed labels and publish Parquet"
    )
    export.add_argument("--inventory-id", required=True)
    export.add_argument("--labelset-id")
    export.add_argument("--annotations", type=Path, required=True)
    export.add_argument("--batch-size", type=int, default=5_000)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "inventory":
            result = build_inventory(
                args.review_root,
                args.inventory_id,
                controls_per_role_per_document=args.controls_per_role_per_document,
                block_batch_size=args.block_batch_size,
                token_batch_size=args.token_batch_size,
            )
            output = (
                resolve_paths().acceptance_root
                / "reflow-prose"
                / result["inventory_id"]
            )
        else:
            result = export_labeled_inventory(
                args.inventory_id,
                args.labelset_id,
                args.annotations,
                batch_size=args.batch_size,
            )
            output = (
                resolve_paths().acceptance_root
                / "reflow-prose"
                / args.inventory_id
                / "labels"
                / result["labelset_id"]
            )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "output": str(output),
                "inventory_id": result["inventory_id"],
                "block_row_count": result["block_row_count"],
                "token_row_count": result["token_row_count"],
                "annotation_required_count": result.get("annotation_required_count"),
                "annotation_count": result.get("annotation_count"),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    main()
