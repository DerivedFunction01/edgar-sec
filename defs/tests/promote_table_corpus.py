"""Promote explicitly reviewed tables into the live corpus."""

from __future__ import annotations

import argparse
from pathlib import Path

from defs.storage import DatasetSpec, pa, read_records, write_table_atomic
from defs.tables import convert_html_tables_to_ascii

ROOT = Path(__file__).parents[2]
LEGACY_PATH = ROOT / "defs/tests/fixtures/tables/validated_table_corpus.parquet"
LIVE_PATH = ROOT / "defs/tests/fixtures/tables/validated_table_corpus_v2.parquet"
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


def _read(path: Path, name: str) -> list[dict]:
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=False)
    selection.add_argument("--id", action="append", dest="ids")
    selection.add_argument("--ids-file", type=Path)
    selection.add_argument("--all-corpus")
    selection.add_argument("--remove-id", action="append", dest="remove_ids")
    parser.add_argument("--exclude-file", type=Path, action="append", default=[])
    args = parser.parse_args()
    if (
        not args.ids
        and not args.ids_file
        and not args.all_corpus
        and not args.remove_ids
    ):
        parser.error(
            "one of --id, --ids-file, --all-corpus, or --remove-id is required"
        )
    legacy = {record["table_id"]: record for record in _read(LEGACY_PATH, "legacy")}
    live = {record["table_id"]: record for record in _read(LIVE_PATH, "live")}
    if args.all_corpus:
        args.ids = [
            table_id
            for table_id, record in legacy.items()
            if record["corpus"] == args.all_corpus
        ]
    if args.ids_file:
        args.ids = [
            line.strip()
            for line in args.ids_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    excluded = {
        line.strip()
        for path in args.exclude_file
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    args.ids = [table_id for table_id in (args.ids or []) if table_id not in excluded]
    remove_ids = set(args.remove_ids or [])
    missing_live = sorted(remove_ids - live.keys())
    if missing_live:
        parser.error(f"table is not in live corpus: {', '.join(missing_live)}")
    live = {
        table_id: record
        for table_id, record in live.items()
        if table_id not in remove_ids
    }
    missing = sorted(set(args.ids) - legacy.keys())
    if missing:
        parser.error(f"unknown table ID(s): {', '.join(missing)}")
    live.update(
        {
            table_id: {
                **legacy[table_id],
                "expected": convert_html_tables_to_ascii(legacy[table_id]["html"]),
            }
            for table_id in args.ids
        }
    )
    table = pa.table(
        {field: [record[field] for record in live.values()] for field in SCHEMA.names}
    )
    write_table_atomic(table, LIVE_PATH, expected_rows=len(live))
    print(
        f"promoted {len(args.ids)} and removed {len(remove_ids)} tables; "
        f"live corpus now has {len(live)} tables"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
