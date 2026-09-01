"""Render a selected table review set into one source-first text file."""

from __future__ import annotations

import argparse
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

from defs.tables import convert_html_tables_to_ascii
from defs.tests.query_table_corpus import LEGACY_CORPUS_PATH, _records


def _ids_from_file(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _render(record: dict) -> str:
    diagnostics = StringIO()
    with redirect_stderr(diagnostics):
        current = convert_html_tables_to_ascii(record["html"], debug=True)
    return "\n".join(
        (
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
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids-file", type=Path)
    parser.add_argument("--id", action="append", dest="ids", default=[])
    parser.add_argument("--corpus-path", type=Path, default=LEGACY_CORPUS_PATH)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.ids_file and not args.ids:
        parser.error("one of --ids-file or --id is required")

    ids = list(args.ids)
    if args.ids_file:
        ids.extend(_ids_from_file(args.ids_file))
    ids = list(dict.fromkeys(ids))
    records = {
        record["table_id"]: record
        for record in _records(args.corpus_path, "review_source")
    }
    missing = sorted(set(ids) - records.keys())
    if missing:
        parser.error(f"unknown table ID(s): {', '.join(missing)}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "\n\n" + "\n\n".join(_render(records[table_id]) for table_id in ids) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(ids)} current table reviews to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
