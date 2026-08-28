"""Scratch probe: DuckDB validation/serialization vs the current merge path.

Part 1 (fidelity): write a rich-type table through DuckDB COPY and through
pyarrow, read both back with a declared pyarrow schema, and require exact
equality (null vs empty preserved, dates/decimals/timestamps exact).

Part 2 (speed, per storage format): build a metadata-like fixture, then time
the current read_records + Python validation + backend serialization against
tuned DuckDB scans (column-pruned, two-pass validation), DuckDB COPY
serialization (ZSTD, bounded threads/memory), and metadata-only read-back.

Run: .venv/bin/python scratch/duckdb_probe/probe.py
"""

from __future__ import annotations

import ctypes
import datetime
import decimal
import gc
import importlib
import resource
import sys
import time
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from defs.storage import DatasetSpec, read_records

OUT = Path(__file__).resolve().parent
CHUNKS = 38
ROWS_PER_CHUNK = 200
FILINGS_PER_ROW = 400
DUCK_THREADS = 6
DUCK_MEMORY_LIMIT = "4GB"

schemas = importlib.import_module("phases.01_metadata_extraction.core.schemas")
checkpoints = importlib.import_module("phases.01_metadata_extraction.core.checkpoints")
storage_mod = importlib.import_module("phases.01_metadata_extraction.core.storage")
SUBMISSION_SCHEMA = schemas.SUBMISSION_METADATA_SCHEMA
SPEC = DatasetSpec(
    name="submission_metadata",
    schema_version=schemas.SCHEMA_VERSION,
    key_field="cik",
    arrow_schema=SUBMISSION_SCHEMA,
)

TIMINGS: list[tuple[str, str, str, float]] = []


def force_reclaim_memory() -> None:
    """Break reference cycles and return freed arenas to the OS (Linux)."""
    gc.collect()
    try:
        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
    except (AttributeError, OSError):
        pass


def rss_now_mb() -> float:
    with open("/proc/self/status", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1000
    return 0.0


def duck_connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(f"SET threads TO {DUCK_THREADS}")
    con.execute(f"SET memory_limit TO '{DUCK_MEMORY_LIMIT}'")
    con.execute("SET preserve_insertion_order = true")
    return con


def timed(stage: str, fmt: str, side: str):
    def deco(fn):
        def wrapper(*args, **kwargs):
            started = time.perf_counter()
            result = fn(*args, **kwargs)
            elapsed = time.perf_counter() - started
            TIMINGS.append((stage, fmt, side, elapsed))
            return result

        return wrapper

    return deco


def duck_type(arrow_type: pa.DataType) -> str:
    if pa.types.is_string(arrow_type):
        return "VARCHAR"
    if pa.types.is_boolean(arrow_type):
        return "BOOLEAN"
    if pa.types.is_int32(arrow_type):
        return "INTEGER"
    if pa.types.is_int64(arrow_type):
        return "BIGINT"
    if pa.types.is_float64(arrow_type):
        return "DOUBLE"
    if pa.types.is_date32(arrow_type):
        return "DATE"
    if pa.types.is_timestamp(arrow_type):
        return "TIMESTAMP"
    if pa.types.is_decimal(arrow_type):
        return f"DECIMAL({arrow_type.precision},{arrow_type.scale})"
    if pa.types.is_list(arrow_type):
        return f"{duck_type(arrow_type.value_type)}[]"
    if pa.types.is_struct(arrow_type):
        inner = ", ".join(
            f'"{field.name}" {duck_type(field.type)}' for field in arrow_type
        )
        return f"STRUCT({inner})"
    raise ValueError(f"unsupported arrow type: {arrow_type}")


def duck_columns_spec(schema: pa.Schema) -> dict[str, str]:
    return {field.name: duck_type(field.type) for field in schema}


def rich_type_table() -> pa.Table:
    """Every type the roadmap hints at: text, numerics, bools, nulls, dates."""
    return pa.table(
        {
            "cik": pa.array(["0000000020", "0000000021", "0000000022"], pa.string()),
            "text": pa.array(["t0", "", None], pa.string()),
            "int32": pa.array([1, None, 3], pa.int32()),
            "int64": pa.array([2**40, 2**41, None], pa.int64()),
            "float64": pa.array([0.5, None, 2.25], pa.float64()),
            "flag": pa.array([True, None, False], pa.bool_()),
            "day": pa.array(
                [datetime.date(2026, 1, 2), None, datetime.date(2025, 12, 31)],
                pa.date32(),
            ),
            "moment": pa.array(
                [
                    datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.UTC),
                    None,
                    datetime.datetime(2025, 12, 31, 23, 59, 59, tzinfo=datetime.UTC),
                ],
                pa.timestamp("us"),
            ),
            "amount": pa.array(
                [
                    None,
                    decimal.Decimal("12.345678900"),
                    decimal.Decimal("-0.000000001"),
                ],
                pa.decimal128(38, 9),
            ),
            "listing": pa.array(
                [
                    [{"ticker": "F", "exchange": "NYSE"}],
                    None,  # null list must stay distinct from empty list
                    [],
                ],
                pa.list_(
                    pa.struct([("ticker", pa.string()), ("exchange", pa.string())])
                ),
            ),
            "profile": pa.array(
                [
                    {"name": "FORD", "fye": None},
                    {"name": None, "fye": "12-31"},
                    None,
                ],
                pa.struct([("name", pa.string()), ("fye", pa.string())]),
            ),
        }
    )


def fidelity_check(con: duckdb.DuckDBPyConnection) -> bool:
    table = rich_type_table()
    arrow_copy = OUT / "fidelity_arrow.parquet"
    duck_copy = OUT / "fidelity_duck.parquet"
    duck_zstd = OUT / "fidelity_duck_zstd.parquet"

    pq.write_table(table, str(arrow_copy))
    con.register("rich", table)
    con.execute(f"COPY rich TO '{duck_copy}' (FORMAT PARQUET)")
    con.execute(
        f"COPY rich TO '{duck_zstd}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 128000)"
    )

    ok = True
    for label, path in (
        ("pyarrow-written", arrow_copy),
        ("duckdb-written", duck_copy),
        ("duckdb-written zstd", duck_zstd),
    ):
        back = pq.read_table(str(path), schema=table.schema)
        same = back.equals(table, check_metadata=False)
        print(f"fidelity {label}: {'EXACT MATCH' if same else 'MISMATCH'}")
        if not same:
            ok = False
            for field in table.schema.names:
                a, b = table[field], back[field]
                if not a.equals(b):
                    print(f"  differing column {field}:")
                    print(f"    expected: {a.to_pylist()}")
                    print(f"    actual:   {b.to_pylist()}")
        read_records(
            str(path),
            "parquet",
            spec=DatasetSpec(
                name="rich",
                schema_version="1.0.0",
                key_field="cik",
                arrow_schema=table.schema,
            ),
        )
    print(
        "fidelity read_records validation: all artifacts pass"
        if ok
        else "read_records failed above"
    )
    return ok


def fixture_row(cik: str, chunk_id: int) -> dict:
    return {
        "cik": cik,
        "snapshot_id": "s",
        "fetched_at": "2026-08-28T00:00:00Z",
        "source_url": f"https://data.sec.gov/submissions/CIK{cik}.json",
        "response_sha256": "0" * 64,
        "byte_count": 1234,
        "schema_version": schemas.SCHEMA_VERSION,
        "status": "ok",
        "error": None,
        "anomalies": [],
        "extra_fields": None,
        "identity": {"name": f"CO {cik}", "former_names": []},
        "classification": {
            "entity_type": None,
            "sic_code": "3711",
            "sic_description": None,
            "owner_org": None,
            "filer_category": None,
        },
        "identifiers": {"ein": None, "lei": None},
        "contact": {
            "phone": None,
            "website": None,
            "investor_website": None,
            "description": None,
        },
        "incorporation": {"state": None, "state_description": None},
        "reporting": {"fiscal_year_end": None},
        "insider_transactions": {"owner_exists": None, "issuer_exists": None},
        "addresses": {"mailing": None, "business": None},
        "listings": [],
        "filings": [
            {
                "accession_number": f"{cik}-26-{j:08d}",
                "accession_number_normalized": f"{cik}260000{j:08d}",
                "filing_date": "2026-01-01",
                "report_date": None,
                "acceptance_datetime": "2026-01-01T10:00:00.000Z",
                "act": "34",
                "form": "10-K",
                "file_number": None,
                "film_number": None,
                "items": None,
                "core_type": None,
                "size": 1000,
                "is_xbrl": None,
                "is_inline_xbrl": None,
                "is_xbrl_numeric": None,
                "primary_document": "a.htm",
                "primary_doc_description": None,
                "archive_url": None,
                "source_section": "recent",
                "source_file": None,
                "source_array_index": j,
            }
            for j in range(FILINGS_PER_ROW)
        ],
        "submission_files": [],
        "input_name": f"CO {cik}",
        "input_fingerprint": "fp",
        "chunk_id": chunk_id,
        "historical_files_total": 0,
        "historical_files_failed": 0,
        "historical_records_total": 0,
    }


def build_fixture(root: Path, fmt: str) -> tuple[list[Path], list[str]]:
    chunk_dir = root / "chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    all_ciks: list[str] = []
    for chunk_id in range(1, CHUNKS + 1):
        start = (chunk_id - 1) * ROWS_PER_CHUNK
        end = start + ROWS_PER_CHUNK - 1
        rows = [
            fixture_row(f"{chunk_id * ROWS_PER_CHUNK + i:010d}", chunk_id)
            for i in range(ROWS_PER_CHUNK)
        ]
        name = checkpoints.chunk_filename(chunk_id, start, end, storage_format=fmt)
        checkpoints.write_checkpoint(rows, str(chunk_dir / name), storage_format=fmt)
        paths.append(chunk_dir / name)
        all_ciks.extend(row["cik"] for row in rows)
    return paths, all_ciks


def python_validate(rows: list[dict], expected_ciks: list[str]) -> list[str]:
    ciks = [row["cik"] for row in rows]
    if sorted(ciks) != sorted(expected_ciks):
        raise ValueError("cik coverage mismatch")
    for row in rows:
        if row["schema_version"] != schemas.SCHEMA_VERSION:
            raise ValueError("schema version")
        if row["input_fingerprint"] != "fp":
            raise ValueError("fingerprint")
        if row["status"] not in schemas.TERMINAL_STATUSES:
            raise ValueError("status")
    seen: set[str] = set()
    duplicates: list[str] = []
    for row in rows:
        for filing in row.get("filings") or []:
            accession = filing.get("accession_number_normalized")
            if accession and accession in seen and accession not in duplicates:
                duplicates.append(accession)
            if accession:
                seen.add(accession)
    return sorted(duplicates)


def reader_expr(fmt: str, paths: list[Path], columns: dict[str, str] | None) -> str:
    file_list = ", ".join(f"'{p}'" for p in paths)
    if fmt == "parquet":
        return f"read_parquet([{file_list}])"
    cols = ", ".join(f"'{name}': '{dtype}'" for name, dtype in columns.items())
    return f"read_ndjson([{file_list}], columns={{{cols}}})"


def duck_validate_fields(con, fmt, paths, columns) -> tuple[int, int, int]:
    src = reader_expr(fmt, paths, columns)
    row = con.execute(
        f"""SELECT count(*), count(DISTINCT cik),
                   count(*) FILTER (schema_version != $1 OR input_fingerprint != $2
                                    OR status NOT IN ('ok', 'partial', 'failed'))
            FROM {src}""",
        [schemas.SCHEMA_VERSION, "fp"],
    ).fetchone()
    return row


def duck_count_duplicates(con, fmt, paths, columns) -> int:
    src = reader_expr(fmt, paths, columns)
    row = con.execute(
        f"""SELECT count(*) - count(DISTINCT acc) FROM (
                SELECT unnest(filings).accession_number_normalized AS acc FROM {src}
            ) WHERE acc IS NOT NULL"""
    ).fetchone()
    return row[0]


def duck_readback_count(con, fmt, paths, columns) -> int:
    if fmt == "parquet":
        src = reader_expr(fmt, paths, columns)
        return con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
    total = 0
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            total += sum(1 for line in fh if line.strip())
    return total


def run_current_baseline(paths, fmt, expected_ciks):
    """Legacy path, fully scoped so its locals die before the duck stages."""

    @timed("load+validate", fmt, "current")
    def load_validate():
        rows = []
        for path in paths:
            rows.extend(read_records(str(path), fmt, spec=SPEC))
        return rows, python_validate(rows, expected_ciks)

    rows, dups = load_validate()

    @timed("serialize", fmt, "current")
    def serialize(rows_arg) -> Path:
        store = storage_mod.make_phase_store(
            "parquet", str(OUT / f"ser_current_{fmt}"), "merge", "fp"
        )
        output = OUT / f"final_current_{fmt}.parquet"
        store.finalize(rows_arg, str(output))
        return output

    output = serialize(rows)

    @timed("readback", fmt, "current")
    def readback():
        return read_records(str(paths[0]), fmt, spec=SPEC)

    readback()
    del rows  # drop the only reference, then hand freed arenas back to the OS
    force_reclaim_memory()
    return output, dups


def ensure_fixture(fmt: str) -> tuple[list[Path], int]:
    extension = "jsonl" if fmt == "jsonl" else "parquet"
    fixture = OUT / f"fixture_{fmt}"
    chunk_dir = fixture / "chunks"
    expected_total = CHUNKS * ROWS_PER_CHUNK
    existing = sorted(chunk_dir.glob(f"*.{extension}")) if chunk_dir.exists() else []
    if len(existing) == CHUNKS:
        print(f"{fmt}: reusing existing fixture ({CHUNKS} files)")
        return existing, expected_total
    print(
        f"building {fmt} fixture: {CHUNKS} chunks x {ROWS_PER_CHUNK} rows x {FILINGS_PER_ROW} filings ..."
    )
    started = time.perf_counter()
    paths, _ciks = build_fixture(fixture, fmt)
    total_bytes = sum(p.stat().st_size for p in paths)
    print(
        f"fixture built in {time.perf_counter() - started:.1f}s "
        f"({len(paths)} files, {total_bytes / 1e6:.0f} MB)"
    )
    return paths, expected_total


def run_format_probe(fmt: str, *, with_baseline: bool = True) -> None:
    print(f"\n=== format: {fmt} ===")
    paths, expected_total = ensure_fixture(fmt)
    columns = duck_columns_spec(SUBMISSION_SCHEMA) if fmt == "jsonl" else None

    current_output = OUT / f"final_current_{fmt}.parquet"
    current_dups: list[str] | None = None
    if with_baseline:
        expected_ciks = [
            f"{chunk * ROWS_PER_CHUNK + i:010d}"
            for chunk in range(1, CHUNKS + 1)
            for i in range(ROWS_PER_CHUNK)
        ]
        current_output, current_dups = run_current_baseline(paths, fmt, expected_ciks)
        print(f"RSS after baseline reclaim: {rss_now_mb():.0f} MB")
    print(f"RSS before duck stages: {rss_now_mb():.0f} MB")

    con = duck_connect()

    @timed("load+validate", fmt, "duckdb")
    def duck_validate():
        n_rows, n_ciks, n_bad = duck_validate_fields(con, fmt, paths, columns)
        if n_rows != expected_total or n_ciks != expected_total:
            raise ValueError(f"coverage mismatch: rows={n_rows} ciks={n_ciks}")
        if n_bad:
            raise ValueError(f"{n_bad} rows fail field validation")
        return duck_count_duplicates(con, fmt, paths, columns)

    duck_dups = duck_validate()
    if current_dups is not None and duck_dups != len(current_dups):
        print(
            f"duplicate counts differ: current={len(current_dups)} duckdb={duck_dups}"
        )
        raise SystemExit(1)

    @timed("serialize", fmt, "duckdb")
    def duck_serialize() -> Path:
        src = reader_expr(fmt, paths, columns)
        output = OUT / f"final_duck_{fmt}.parquet"
        # Scanning files directly: no Python-side rows exist to drop. If a
        # future integration registers an Arrow table instead, delete the
        # Python reference immediately after COPY consumes it.
        con.execute(
            f"""COPY (SELECT * FROM {src} ORDER BY chunk_id, cik)
                TO '{output}'
                (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 128000)"""
        )
        return output

    duck_output = duck_serialize()

    @timed("readback", fmt, "duckdb")
    def duck_readback():
        # Serialized output is always Parquet: count via metadata, no data read.
        return pq.ParquetFile(str(duck_output)).metadata.num_rows

    duck_readback()
    con.close()
    force_reclaim_memory()
    print(f"RSS after duck stages: {rss_now_mb():.0f} MB")

    if with_baseline:
        same_final = pq.read_table(str(duck_output), schema=SUBMISSION_SCHEMA).equals(
            pq.read_table(str(current_output), schema=SUBMISSION_SCHEMA),
            check_metadata=False,
        )
        duck_bytes = duck_output.stat().st_size
        print(
            f"serialized output equality: {'EXACT MATCH' if same_final else 'MISMATCH'}"
        )
        print(
            f"serialized size: current {current_output.stat().st_size / 1e6:.0f} MB"
            f" vs duckdb zstd {duck_bytes / 1e6:.0f} MB"
        )


def main() -> int:
    duck_only = "--duck-only" in sys.argv
    con = duck_connect()
    print(f"duckdb {duckdb.__version__}")
    con.close()
    if not duck_only and not fidelity_check(duck_connect()):
        return 1
    for fmt in ("parquet", "jsonl"):
        run_format_probe(fmt, with_baseline=not duck_only)

    print(f"\n{'stage':<16} {'format':<8} {'current':>10} {'duckdb':>10}")
    stages = list(dict.fromkeys((s, f) for s, f, _, _ in TIMINGS))
    for stage, fmt in stages:
        cur = next(
            (
                t
                for s, f, side, t in TIMINGS
                if s == stage and f == fmt and side == "current"
            ),
            None,
        )
        duc = next(
            (
                t
                for s, f, side, t in TIMINGS
                if s == stage and f == fmt and side == "duckdb"
            ),
            None,
        )
        cur_s = f"{cur:8.2f}s" if cur is not None else "-"
        duc_s = f"{duc:8.2f}s" if duc is not None else "-"
        print(f"{stage:<16} {fmt:<8} {cur_s:>10} {duc_s:>10}")

    for fmt in ("parquet", "jsonl"):
        total_cur = sum(
            t for s, f, side, t in TIMINGS if f == fmt and side == "current"
        )
        total_duc = sum(t for s, f, side, t in TIMINGS if f == fmt and side == "duckdb")
        if total_duc:
            print(
                f"{'TOTAL ' + fmt:<16} {total_cur:8.2f}s {total_duc:8.2f}s  ({total_cur / total_duc:.1f}x)"
            )
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1000
    mode = "duck-only" if duck_only else "baseline + duckdb"
    print(f"peak RSS ({mode}): {peak_mb:.0f} MB")
    print("\nPROBE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
