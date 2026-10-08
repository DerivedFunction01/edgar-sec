"""Inventory query command."""

from __future__ import annotations

import argparse
import json
from typing import Any

from edgar_sec.foundation.runtime.render import (
    Grid,
    KeyValueRow,
    ProseRow,
    render_output,
)
from edgar_sec.pipelines.document_inventory.paths import InventoryPaths
from edgar_sec.pipelines.document_inventory.snapshot import reader

from .common import resolve_artifacts_root


def cmd_query(args: argparse.Namespace) -> int:
    """Query active document inventory snapshots."""
    root = resolve_artifacts_root(args.artifacts_root)
    snapshots_root = InventoryPaths(root).snapshots_root

    results: list[dict[str, Any]] = []
    if args.accession:
        acc = reader.get_active_accession(snapshots_root, args.accession)
        if acc:
            entries = reader.get_active_entries(snapshots_root, args.accession)
            acc_copy = dict(acc)
            acc_copy["entries"] = entries
            results.append(acc_copy)
    elif args.filing_cik and not (args.form or args.source_cik):
        results = reader.get_accessions_by_cik(snapshots_root, args.filing_cik)
    elif args.source_cik and not (args.form or args.filing_cik):
        results = reader.get_accessions_by_source_cik(snapshots_root, args.source_cik)
    else:
        results = reader.query_accessions(
            snapshots_root,
            form=args.form,
            filing_cik=args.filing_cik,
            source_cik=args.source_cik,
            limit=args.limit,
        )

    payload = {
        "count": len(results),
        "results": results,
    }

    if getattr(args, "json", False):
        print(
            json.dumps(
                {"schema_version": 1, "command": "inventory query", **payload},
                sort_keys=True,
                ensure_ascii=False,
            )
        )
    else:
        if not results:
            render_output(
                [ProseRow("no matching accessions found")],
                title="Inventory Query",
            )
        elif len(results) == 1 and "entries" in results[0]:
            item = results[0]
            acc_fields = [
                KeyValueRow(str(k), str(v)) for k, v in item.items() if k != "entries"
            ]
            entries = item.get("entries", [])
            headers = ("document", "type", "description", "size")
            rows = tuple(
                (
                    str(e.get("document", "")),
                    str(e.get("type", "")),
                    str(e.get("description", "")),
                    str(e.get("size", "")),
                )
                for e in entries
            )
            render_output(
                [*acc_fields, Grid(headers, rows)],
                title=f"Accession Details ({item.get('accession', '')})",
            )
        else:
            headers = ("accession", "form", "filing_date", "filing_cik")
            rows = tuple(
                (
                    str(r.get("accession", "")),
                    str(r.get("form", "")),
                    str(r.get("filing_date", "")),
                    str(r.get("filing_cik", "")),
                )
                for r in results
            )
            render_output(
                [
                    Grid(headers, rows),
                    KeyValueRow("total_results", str(len(results))),
                ],
                title="Query Results",
            )

    return 0
