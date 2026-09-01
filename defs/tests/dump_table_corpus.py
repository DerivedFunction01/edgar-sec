"""Dump the reviewed table corpus to one readable ASCII inspection file."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from defs.runtime.paths import resolve_paths
from defs.tables import convert_html_tables_to_ascii
from defs.tests.query_table_corpus import _records


def _default_output() -> Path:
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return (
        resolve_paths().test_run_root("defs", "table-corpus-dump", run_id)
        / "validated_table_corpus.txt"
    )


def _render(records: list[dict], *, corpus: str | None, render_current: bool) -> str:
    lines = [
        "CURRENT TABLE CORPUS RENDER" if render_current else "VALIDATED TABLE CORPUS",
        f"Tables: {len(records)}",
        f"Corpus filter: {corpus or '(all)'}",
        (
            "Converted field: current converter applied to html"
            if render_current
            else "Converted field: expected"
        ),
        "",
    ]
    for index, record in enumerate(records):
        if index:
            lines.extend(("", "=" * 100, ""))
        lines.extend(
            (
                f"TABLE {index + 1}/{len(records)}",
                f"ID: {record['table_id']}",
                f"Corpus: {record['corpus']}",
                f"Source: {record['source_path']}",
                f"Source SHA256: {record['source_sha256']}",
                "",
                (
                    convert_html_tables_to_ascii(record["html"])
                    if render_current
                    else record["expected"]
                ).rstrip("\n"),
            )
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", help="dump only one filing corpus")
    parser.add_argument("--limit", type=int, help="limit records after filtering")
    parser.add_argument(
        "--first", type=int, help="select the first N corpus records before filtering"
    )
    parser.add_argument(
        "--whitelist",
        type=Path,
        help="newline-delimited table IDs to include",
    )
    parser.add_argument(
        "--blacklist",
        type=Path,
        help="newline-delimited table IDs to exclude",
    )
    parser.add_argument(
        "--render-current",
        action="store_true",
        help="convert each stored raw HTML table with the current converter",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="output path; use '-' for stdout (default: generated test-run path)",
    )
    args = parser.parse_args(argv)

    records = _records()
    if args.first is not None:
        if args.first <= 0:
            parser.error("--first must be positive")
        records = records[: args.first]
    if args.corpus:
        records = [record for record in records if record["corpus"] == args.corpus]
    if args.whitelist:
        allowed = {
            line.strip()
            for line in args.whitelist.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        records = [record for record in records if record["table_id"] in allowed]
    if args.blacklist:
        blocked = {
            line.strip()
            for line in args.blacklist.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        records = [record for record in records if record["table_id"] not in blocked]
    if args.limit is not None:
        if args.limit <= 0:
            parser.error("--limit must be positive")
        records = records[: args.limit]
        if not records:
            parser.error(f"unknown or empty corpus: {args.corpus}")

    rendered = _render(records, corpus=args.corpus, render_current=args.render_current)
    if args.output and str(args.output) == "-":
        sys.stdout.write(rendered)
        return 0

    output = args.output or _default_output()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    print(f"Wrote {len(records)} tables to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
