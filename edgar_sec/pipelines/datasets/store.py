"""DuckDB-side loads of dataset vintages into the datasets store.

TSV members are extracted to files and read by DuckDB itself; no Python
code materializes a data row. Rows carry set, vintage, and archive SHA,
so a re-posted vintage is a distinct slice, never a mutation.
"""

from __future__ import annotations

import csv
import zipfile
from dataclasses import dataclass
from pathlib import Path

from edgar_sec.infra.storage.duckdb import connect, sql_identifier, sql_literal

from .specs import DatasetSpec

VINTAGES_RELATION = "dataset_vintages"
VINTAGE_TABLES_RELATION = "dataset_vintage_tables"
POPULATION_RELATION = "bdc_population"

_META_COLUMNS = ("set_id", "vintage", "archive_sha")


@dataclass(frozen=True, slots=True)
class LoadedTable:
    """One loaded member: its relation, source line count, and row count."""

    relation: str
    member: str
    source_rows: int
    loaded_rows: int


@dataclass(frozen=True, slots=True)
class VintageLoad:
    """The outcome of loading one vintage archive into the store."""

    set_id: str
    vintage: str
    archive_sha: str
    tables: tuple[LoadedTable, ...]


def open_store(store_file: Path):
    """Open the datasets store, creating its directory and meta relations."""
    store_file.parent.mkdir(parents=True, exist_ok=True)
    con = connect(database=store_file)
    con.execute(
        f"CREATE TABLE IF NOT EXISTS {VINTAGES_RELATION} ("
        "set_id VARCHAR, vintage VARCHAR, archive_sha VARCHAR, "
        "source_url VARCHAR, loaded_at VARCHAR)"
    )
    con.execute(
        f"CREATE TABLE IF NOT EXISTS {VINTAGE_TABLES_RELATION} ("
        "set_id VARCHAR, vintage VARCHAR, archive_sha VARCHAR, "
        "relation VARCHAR, member VARCHAR, source_rows BIGINT, "
        "loaded_rows BIGINT)"
    )
    return con


def extract_members(
    archive_path: Path, spec: DatasetSpec, dest_dir: Path
) -> dict[str, tuple[Path, int]]:
    """Extract a vintage's loadable TSV members to files; count their lines.

    Returns {member_name: (extracted_path, line_count)}. Line counts are
    tallied while streaming each member out, independent of the load.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    extracted: dict[str, tuple[Path, int]] = {}
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            if spec.relation_for(info.filename) is None:
                continue
            target = dest_dir / info.filename.replace("/", "__")
            lines = 0
            with archive.open(info) as src, open(target, "wb") as dst:
                while True:
                    chunk = src.readline()
                    if not chunk:
                        break
                    dst.write(chunk)
                    lines += 1
            extracted[info.filename] = (target, lines)
    return extracted


def load_vintage(
    con,
    spec: DatasetSpec,
    archive_path: Path,
    *,
    vintage: str,
    archive_sha: str,
    source_url: str,
    loaded_at: str,
    work_dir: Path,
) -> VintageLoad:
    """Load one vintage archive's members into the store, DuckDB-side."""
    extracted = extract_members(archive_path, spec, work_dir)
    tables: list[LoadedTable] = []
    for member, (path, source_lines) in sorted(extracted.items()):
        relation = spec.relation_for(member)
        assert relation is not None
        _load_member(con, spec, relation, path, vintage, archive_sha)
        loaded = int(
            con.execute(
                f"SELECT count(*) FROM {sql_identifier(relation)} "
                "WHERE set_id = ? AND vintage = ? AND archive_sha = ?",
                [spec.set_id, vintage, archive_sha],
            ).fetchone()[0]
        )
        tables.append(
            LoadedTable(
                relation=relation,
                member=member,
                source_rows=max(source_lines - 1, 0),
                loaded_rows=loaded,
            )
        )
    con.execute(
        f"DELETE FROM {VINTAGES_RELATION} "
        "WHERE set_id = ? AND vintage = ? AND archive_sha = ?",
        [spec.set_id, vintage, archive_sha],
    )
    con.execute(
        f"INSERT INTO {VINTAGES_RELATION} VALUES (?, ?, ?, ?, ?)",
        [spec.set_id, vintage, archive_sha, source_url, loaded_at],
    )
    con.execute(
        f"DELETE FROM {VINTAGE_TABLES_RELATION} "
        "WHERE set_id = ? AND vintage = ? AND archive_sha = ?",
        [spec.set_id, vintage, archive_sha],
    )
    for table in tables:
        con.execute(
            f"INSERT INTO {VINTAGE_TABLES_RELATION} VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                spec.set_id,
                vintage,
                archive_sha,
                table.relation,
                table.member,
                table.source_rows,
                table.loaded_rows,
            ],
        )
    return VintageLoad(
        set_id=spec.set_id,
        vintage=vintage,
        archive_sha=archive_sha,
        tables=tuple(tables),
    )


def _load_member(
    con,
    spec: DatasetSpec,
    relation: str,
    path: Path,
    vintage: str,
    archive_sha: str,
) -> None:
    """Replace one (set, vintage, sha) slice of a relation from a TSV file."""
    con.execute(
        f"CREATE TABLE IF NOT EXISTS {sql_identifier(relation)} AS "
        f"SELECT {sql_literal(spec.set_id)} AS set_id, "
        f"{sql_literal(vintage)} AS vintage, "
        f"{sql_literal(archive_sha)} AS archive_sha, * FROM "
        f"read_csv({sql_literal(str(path))}, header = true, sep = '\\t', "
        "all_varchar = true) WHERE false"
    )
    con.execute(
        f"DELETE FROM {sql_identifier(relation)} "
        "WHERE set_id = ? AND vintage = ? AND archive_sha = ?",
        [spec.set_id, vintage, archive_sha],
    )
    con.execute(
        f"INSERT INTO {sql_identifier(relation)} "
        f"SELECT {sql_literal(spec.set_id)}, {sql_literal(vintage)}, "
        f"{sql_literal(archive_sha)}, * FROM "
        f"read_csv({sql_literal(str(path))}, header = true, sep = '\\t', "
        "all_varchar = true)"
    )


def load_bdc_population(con, yearly_csvs: dict[int, Path], *, loaded_at: str) -> int:
    """Load BDC Report CSVs as the population reference relation.

    Rows keep their report year; the union over years is the register,
    because a single year's file is a mid-year snapshot, not a register.
    """
    con.execute(f"DROP TABLE IF EXISTS {POPULATION_RELATION}")
    con.execute(
        f"CREATE TABLE {POPULATION_RELATION} ("
        "cik VARCHAR, registrant_name VARCHAR, file_number VARCHAR, "
        "city VARCHAR, state VARCHAR, zip_code VARCHAR, "
        "last_filing_date VARCHAR, last_filing_type VARCHAR, "
        "report_year BIGINT, loaded_at VARCHAR)"
    )
    total = 0
    for year, path in sorted(yearly_csvs.items()):
        rows = _bdc_report_rows(path, year, loaded_at)
        con.executemany(
            f"INSERT INTO {POPULATION_RELATION} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        total += len(rows)
    return total


def _bdc_report_rows(path: Path, year: int, loaded_at: str) -> list[tuple]:
    """Normalize one BDC Report CSV's rows; column spellings vary by year."""
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = {name.strip().lower(): name for name in reader.fieldnames or []}

        def pick(*names: str) -> str | None:
            for name in names:
                if name in fields:
                    return fields[name]
            return None

        cik_col = pick("cik")
        if cik_col is None:
            raise ValueError(f"BDC report {path} has no CIK column")
        cols = {
            "name": pick("registrant_name", "registrant name"),
            "file_number": pick("file_no", "file number", "file_number"),
            "city": pick("city"),
            "state": pick("state"),
            "zip": pick("zip_code", "zip code"),
            "date": pick("filing date", "last filling date", "last_filing_date"),
            "type": pick("filing type", "last filling type", "last_filing_type"),
        }
        rows = []
        for raw in reader:
            cik = str(raw[cik_col]).strip()
            if not cik:
                continue
            rows.append(
                (
                    cik.zfill(10),
                    _cell(raw, cols["name"]),
                    _cell(raw, cols["file_number"]),
                    _cell(raw, cols["city"]),
                    _cell(raw, cols["state"]),
                    _cell(raw, cols["zip"]),
                    _cell(raw, cols["date"]),
                    _cell(raw, cols["type"]),
                    year,
                    loaded_at,
                )
            )
        return rows


def _cell(raw: dict, column: str | None) -> str | None:
    if column is None:
        return None
    value = raw.get(column)
    return str(value).strip() if value is not None and str(value).strip() else None


__all__ = [
    "POPULATION_RELATION",
    "VINTAGES_RELATION",
    "VINTAGE_TABLES_RELATION",
    "LoadedTable",
    "VintageLoad",
    "extract_members",
    "load_bdc_population",
    "load_vintage",
    "open_store",
]
