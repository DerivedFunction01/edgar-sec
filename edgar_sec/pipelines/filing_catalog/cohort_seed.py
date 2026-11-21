from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from edgar_sec.engine.selection.policy import (
    SEED_FILER_COLUMNS,
    _csv_field,
    compute_seed_fingerprint_rows,
)
from edgar_sec.infra.storage.cohort.models import CohortRecord
from edgar_sec.infra.storage.duckdb import connect, sql_literal


@dataclass(frozen=True, slots=True)
class SeedFilerSource:
    relation_sql: str
    count: int
    fingerprint: str

    @property
    def cik_relation_sql(self) -> str:
        return f"SELECT cik FROM ({self.relation_sql})"

    def write_csv(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with (
            connect() as con,
            destination.open("w", encoding="utf-8", newline="") as handle,
        ):
            handle.write(",".join(SEED_FILER_COLUMNS) + "\n")
            cursor = con.execute(
                f"SELECT cik, seed_group, coverage_tags, notes "
                f"FROM ({self.relation_sql}) ORDER BY cik"
            )
            while row := cursor.fetchone():
                handle.write(",".join(_csv_field(str(value)) for value in row))
                handle.write("\n")
        return destination


def _validated_source(relation_sql: str, description: str) -> SeedFilerSource:
    try:
        with connect() as con:
            count, distinct_count, invalid_count = con.execute(
                f"SELECT COUNT(*), COUNT(DISTINCT cik), "
                "COUNT(*) FILTER (WHERE cik IS NULL OR length(cik) != 10 "
                "OR NOT regexp_full_match(cik, '[0-9]{10}')) "
                f"FROM ({relation_sql})"
            ).fetchone()
            if count != distinct_count:
                raise ValueError("seed source contains duplicate CIKs")
            if invalid_count:
                raise ValueError("seed source contains invalid CIKs")
            cursor = con.execute(
                "SELECT cik, seed_group, coverage_tags, notes "
                f"FROM ({relation_sql}) ORDER BY cik"
            )

            def rows() -> Iterator[tuple[str, ...]]:
                while row := cursor.fetchone():
                    yield tuple(str(value or "") for value in row)

            fingerprint = compute_seed_fingerprint_rows(rows())
        return SeedFilerSource(relation_sql, int(count), fingerprint)
    except Exception as error:
        raise ValueError(f"unable to read {description}: {error}") from error


def cohort_seed_filers(record: CohortRecord, dataset: Path) -> SeedFilerSource:
    path = sql_literal(str(dataset.resolve()))
    relation = f"""
        SELECT CAST(cik_padded AS VARCHAR) AS cik,
               'cohort' AS seed_group,
               {sql_literal(record.name or record.cohort_id)} AS coverage_tags,
               {sql_literal(f"From cohort {record.cohort_id}")} AS notes
        FROM read_parquet({path})
    """
    source = _validated_source(relation, f"cohort seeds {record.cohort_id!r}")
    if source.count != record.row_count:
        raise ValueError(
            f"cohort seed count mismatch for {record.cohort_id!r}: "
            f"{source.count} != {record.row_count}"
        )
    return source


def seed_filer_csv_source(path: str | Path) -> SeedFilerSource:
    source_path = Path(path).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"plan seed sidecar not found: {source_path}")
    escaped_path = sql_literal(str(source_path))
    relation = f"""
        SELECT trim(cik) AS cik,
               COALESCE(NULLIF(trim(seed_group), ''), 'default') AS seed_group,
               COALESCE(trim(coverage_tags), '') AS coverage_tags,
               COALESCE(trim(notes), '') AS notes
        FROM read_csv({escaped_path}, header = true, all_varchar = true)
        WHERE trim(cik) <> ''
    """
    return _validated_source(relation, f"seed sidecar {source_path}")
