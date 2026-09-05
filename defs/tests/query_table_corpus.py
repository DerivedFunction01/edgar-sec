"""Inspect the tracked table corpus without running the corpus test."""

from __future__ import annotations

import argparse
import difflib
import re
from pathlib import Path

from defs.storage import DatasetSpec, pa, read_records
from defs.tables.ascii_html_v2 import convert_html_tables_to_ascii_v2

ROOT = Path(__file__).parents[2]
CORPUS_PATH = ROOT / "defs/tests/fixtures/tables/validated_table_corpus_v2.parquet"
SCHEMA = pa.schema(
    [
        ("corpus", pa.string()),
        ("table_id", pa.string()),
        ("source_sha256", pa.string()),
        ("source_path", pa.string()),
        ("html", pa.string()),
        ("expected", pa.string()),
    ]
)


def _records(
    path: Path = CORPUS_PATH, name: str = "validated_table_corpus_v2"
) -> list[dict]:
    return read_records(
        path,
        "parquet",
        spec=DatasetSpec(
            name=name,
            schema_version="1",
            key_field="table_id",
            arrow_schema=SCHEMA,
            required_fields=tuple(SCHEMA.names),
        ),
    )


def format_side_by_side(
    left_text: str,
    right_text: str,
    *,
    left_title: str = "EXPECTED (GOLDEN)",
    right_title: str = "V2 RENDER",
    left_width: int | None = None,
) -> str:
    """Format two multiline strings side-by-side separated by a vertical bar."""
    left_lines = left_text.strip("\n").splitlines()
    right_lines = right_text.strip("\n").splitlines()

    if left_width is None:
        max_left = max((len(line) for line in left_lines), default=0)
        left_width = max(max_left, len(left_title), 20)

    header = f"{left_title:<{left_width}} | {right_title}"
    divider = f"{'-' * left_width}-+-{'-' * max(len(right_title), 40)}"
    rows = [header, divider]

    max_rows = max(len(left_lines), len(right_lines))
    for i in range(max_rows):
        l_line = left_lines[i] if i < len(left_lines) else ""
        r_line = right_lines[i] if i < len(right_lines) else ""
        rows.append(f"{l_line:<{left_width}} | {r_line}")

    return "\n".join(rows)


def format_diff(
    expected_text: str,
    actual_text: str,
    *,
    fromfile: str = "expected (golden)",
    tofile: str = "v2 render",
) -> str:
    """Generate a unified diff between expected and actual text."""
    diff = list(
        difflib.unified_diff(
            expected_text.splitlines(keepends=True),
            actual_text.splitlines(keepends=True),
            fromfile=fromfile,
            tofile=tofile,
        )
    )
    if not diff:
        return "(no differences)\n"
    return "".join(diff)


def _print_window(
    text: str, *, head: int | None, tail: int | None, offset: int
) -> None:
    lines = text.splitlines()
    if head is not None:
        lines = lines[:head]
    elif tail is not None:
        lines = lines[-tail:]
    else:
        lines = lines[offset:]
    for number, line in enumerate(lines, start=offset + 1 if tail is None else 1):
        print(f"{number}: {line}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", help="exact table ID")
    parser.add_argument(
        "--grep", help="case-insensitive regex searched in corpus fields"
    )
    parser.add_argument("--corpus", help="limit --grep results to one filing corpus")
    parser.add_argument(
        "--show",
        choices=("expected", "html", "v2", "diff", "side-by-side"),
        default="expected",
        help="what to display for matching tables (default: expected)",
    )
    parser.add_argument(
        "--search-in",
        choices=("html", "expected", "both"),
        default="both",
        help="field searched by --grep (default: both)",
    )
    parser.add_argument("--head", type=int, help="show only the first N lines")
    parser.add_argument("--tail", type=int, help="show only the last N lines")
    parser.add_argument("--offset", type=int, default=0, help="start line offset")
    parser.add_argument(
        "--context", type=int, default=0, help="lines around each grep match"
    )
    args = parser.parse_args(argv)
    if not args.id and not args.grep:
        parser.error("one of --id or --grep is required")
    if args.head is not None and args.tail is not None:
        parser.error("--head and --tail cannot be combined")
    if args.offset < 0 or args.context < 0:
        parser.error("--offset and --context must be non-negative")

    records = _records()
    if args.id:
        records = [record for record in records if record["table_id"] == args.id]
    if args.grep:
        pattern = re.compile(args.grep, re.IGNORECASE)

        def matches(record: dict) -> bool:
            fields = (
                (args.search_in,) if args.search_in != "both" else ("html", "expected")
            )
            return any(pattern.search(record[field]) for field in fields)

        records = [
            record
            for record in records
            if (not args.corpus or record["corpus"] == args.corpus) and matches(record)
        ]
    if not records:
        print("No matching tables.")
        return 1

    for index, record in enumerate(records):
        if index:
            print("\n" + "=" * 80)
        print(f"ID: {record['table_id']}")
        print(f"Corpus: {record['corpus']}")
        print(f"Source: {record['source_path']}")

        if args.show == "expected":
            text = record["expected"]
        elif args.show == "html":
            text = record["html"]
        elif args.show == "v2":
            text = convert_html_tables_to_ascii_v2(record["html"])
        elif args.show == "diff":
            v2_render = convert_html_tables_to_ascii_v2(record["html"])
            text = format_diff(record["expected"], v2_render)
        elif args.show == "side-by-side":
            v2_render = convert_html_tables_to_ascii_v2(record["html"])
            text = format_side_by_side(record["expected"], v2_render)
        else:
            text = record["expected"]

        if args.grep and args.context:
            fields = (
                (args.search_in,) if args.search_in != "both" else ("html", "expected")
            )
            for field in fields:
                lines = record[field].splitlines()
                hits = [
                    i
                    for i, line in enumerate(lines)
                    if re.search(args.grep, line, re.IGNORECASE)
                ]
                if hits:
                    if len(fields) > 1:
                        print(f"[{field}]")
                    selected = sorted(
                        {
                            i
                            for hit in hits
                            for i in range(
                                max(0, hit - args.context),
                                min(len(lines), hit + args.context + 1),
                            )
                        }
                    )
                    for line_number in selected:
                        print(f"{line_number + 1}: {lines[line_number]}")
        else:
            _print_window(text, head=args.head, tail=args.tail, offset=args.offset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
