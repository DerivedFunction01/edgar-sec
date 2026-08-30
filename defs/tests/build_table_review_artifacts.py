"""Create source-first review bundles for selected corpus tables."""

from __future__ import annotations

import argparse
import json
from contextlib import redirect_stderr
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

from defs.runtime.paths import resolve_paths
from defs.tables import convert_html_tables_to_ascii
from defs.tests.query_table_corpus import LEGACY_CORPUS_PATH, _records


def _default_root() -> Path:
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return resolve_paths().test_run_root("defs", "table-reviews", run_id)


def _bundle(record: dict) -> str:
    diagnostics = StringIO()
    with redirect_stderr(diagnostics):
        current = convert_html_tables_to_ascii(record["html"], debug=True)
    return "\n".join(
        (
            "TABLE REVIEW ARTIFACT",
            f"ID: {record['table_id']}",
            f"Corpus: {record['corpus']}",
            f"Source: {record['source_path']}",
            f"Source SHA256: {record['source_sha256']}",
            "",
            "=== ORIGINAL HTML TABLE ===",
            record["html"].rstrip(),
            "",
            "=== PIPELINE DIAGNOSTICS ===",
            diagnostics.getvalue().rstrip(),
            "",
            "=== CURRENT ASCII RENDER ===",
            current.rstrip(),
            "",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--id", action="append", dest="ids")
    selection.add_argument("--corpus")
    selection.add_argument("--all", action="store_true")
    parser.add_argument(
        "--legacy", action="store_true", help="read the legacy full corpus"
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    source_records = (
        _records(LEGACY_CORPUS_PATH, "validated_table_corpus_legacy")
        if args.legacy
        else _records()
    )
    records = {record["table_id"]: record for record in source_records}
    if args.all:
        selected = list(records.values())
    elif args.corpus:
        selected = [
            record for record in records.values() if record["corpus"] == args.corpus
        ]
    else:
        selected = [records[table_id] for table_id in args.ids if table_id in records]
    ids = [record["table_id"] for record in selected]
    missing = sorted(set(args.ids or []) - records.keys())
    if missing:
        parser.error(f"unknown table ID(s): {', '.join(missing)}")
    if not selected:
        parser.error("selection matched no tables")
    root = args.output or _default_root()
    root.mkdir(parents=True, exist_ok=True)
    manifest = []
    for record in selected:
        table_id = record["table_id"]
        (root / f"{table_id}.txt").write_text(_bundle(record), encoding="utf-8")
        manifest.append(
            {
                "table_id": table_id,
                "corpus": record["corpus"],
                "source_path": record["source_path"],
                "source_sha256": record["source_sha256"],
                "artifact": f"{table_id}.txt",
                "status": None,
                "pattern": None,
                "issues": [],
                "evidence": None,
                "recommendation": None,
            }
        )
    (root / "review_manifest.jsonl").write_text(
        "".join(json.dumps(entry, sort_keys=True) + "\n" for entry in manifest),
        encoding="utf-8",
    )
    print(f"Wrote {len(ids)} review artifacts and manifest to {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
