"""Snapshot relation schemas and the DuckDB merge-relation construction."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa

from edgar_sec.domain.document_inventory.schemas import ENTRY_SCHEMA
from edgar_sec.infra.storage.dag.operator.doctor import _resolve_part_path
from edgar_sec.infra.storage.dag.working.traversal import walk_lineage
from edgar_sec.infra.storage.duckdb import sql_identifier, sql_path_list
from edgar_sec.pipelines.document_inventory.checkpoint import OUTCOME_SCHEMA
from edgar_sec.pipelines.document_inventory.paths import InventoryPaths
from edgar_sec.pipelines.document_inventory.snapshot.contracts.errors import (
    ValidationFailedError,
)
from edgar_sec.pipelines.document_inventory.snapshot.projection.projection_relations import (
    COHORT_ACCESSIONS_SCHEMA,
)
from edgar_sec.pipelines.document_inventory.snapshot.contracts.schema import (
    SNAPSHOT_ACCESSION_SOURCES_SCHEMA,
    SNAPSHOT_ACCESSIONS_SCHEMA,
    SNAPSHOT_ENUMERATION_SCHEMA,
)


_RELATION_SCHEMAS = {
    "accessions": SNAPSHOT_ACCESSIONS_SCHEMA,
    "entries": ENTRY_SCHEMA,
    "accession_sources": SNAPSHOT_ACCESSION_SOURCES_SCHEMA,
    "accession_enumeration": SNAPSHOT_ENUMERATION_SCHEMA,
}


_RELATION_KEYS = {
    "accessions": "accession",
    "entries": "accession",
    "accession_sources": "source_cik",
    "accession_enumeration": "accession",
}


def _view(con, name: str, files: list[Path], schema: pa.Schema) -> None:
    if files:
        con.execute(
            f"CREATE TEMP VIEW {sql_identifier(name)} AS SELECT * FROM "
            f"read_parquet({sql_path_list([str(path) for path in files])}, hive_partitioning=false)"
        )
    else:
        empty_name = f"empty_{name}"
        con.register(empty_name, pa.Table.from_batches([], schema=schema))
        con.execute(
            f"CREATE TEMP VIEW {sql_identifier(name)} AS "
            f"SELECT * FROM {sql_identifier(empty_name)}"
        )


def _parent_relation_files(
    paths: InventoryPaths,
    parent_snapshot_id: str | None,
    relation: str,
) -> list[Path]:
    if not parent_snapshot_id:
        return []
    lineage = walk_lineage(paths.snapshots_root, parent_snapshot_id)
    files: list[Path] = []
    for node in lineage.nodes:
        for part in node.relations.get(relation, ()):
            part_path = _resolve_part_path(
                paths.snapshots_root, node.snapshot_id, part.path
            )
            if part_path.is_file():
                files.append(part_path)
    return files


def _create_merge_relations(
    con,
    parent_snapshot_id: str | None,
    paths: InventoryPaths,
    cohort_accessions: Path,
    cohort_sources: Path,
    staged_outcomes: Path,
    staged_entries: Path,
    eligible_outcomes: list[Path],
    candidate_entries: Path,
    new_sources: Path,
    source_identity: str,
    refresh: bool,
) -> None:
    for name, schema in _RELATION_SCHEMAS.items():
        files = _parent_relation_files(paths, parent_snapshot_id, name)
        _view(con, f"parent_{name}", files, schema)
    _view(
        con,
        "cohort_accessions",
        [cohort_accessions],
        COHORT_ACCESSIONS_SCHEMA,
    )
    _view(
        con,
        "cohort_sources",
        [cohort_sources],
        SNAPSHOT_ACCESSION_SOURCES_SCHEMA,
    )
    _view(con, "staged_outcomes", [staged_outcomes], OUTCOME_SCHEMA)
    _view(con, "staged_entries", [staged_entries], ENTRY_SCHEMA)
    _view(con, "eligible_outcomes", eligible_outcomes, OUTCOME_SCHEMA)
    _view(con, "candidate_entries", [candidate_entries], ENTRY_SCHEMA)
    _view(
        con,
        "new_sources",
        [new_sources],
        SNAPSHOT_ACCESSION_SOURCES_SCHEMA,
    )

    con.execute(
        "CREATE TEMP TABLE invalid_outcomes AS SELECT accession, status FROM staged_outcomes "
        "WHERE status IS NULL OR status NOT IN (?, ?)",
        ["parsed", "parsed_empty"],
    )
    if con.execute("SELECT count(*) FROM invalid_outcomes").fetchone()[0]:
        status = con.execute("SELECT status FROM invalid_outcomes LIMIT 1").fetchone()[
            0
        ]
        raise ValidationFailedError(f"refusal outcome blocks publication: {status!r}")
    if con.execute(
        "SELECT count(*) FROM staged_outcomes o ANTI JOIN cohort_accessions c USING(accession)"
    ).fetchone()[0]:
        raise ValidationFailedError("an outcome is absent from the cohort projection")
    if con.execute(
        "SELECT count(*) FROM staged_outcomes o JOIN cohort_accessions c USING(accession) "
        "WHERE o.index_url IS DISTINCT FROM c.index_url"
    ).fetchone()[0]:
        raise ValidationFailedError("outcome URL differs from its projected accession")
    if con.execute(
        "SELECT count(*) FROM (SELECT accession FROM cohort_accessions GROUP BY accession "
        "HAVING count(*) > 1)"
    ).fetchone()[0]:
        raise ValidationFailedError(
            "cohort accession projection contains duplicate accessions"
        )
    if con.execute(
        "SELECT count(*) FROM (SELECT accession, source_cik FROM cohort_sources "
        "GROUP BY accession, source_cik HAVING count(*) > 1)"
    ).fetchone()[0]:
        raise ValidationFailedError("cohort source projection contains duplicate edges")
    if con.execute(
        "SELECT count(*) FROM (SELECT o.accession FROM staged_outcomes o "
        "LEFT JOIN staged_entries e USING(accession) GROUP BY o.accession, o.entry_count "
        "HAVING o.entry_count IS NULL OR o.entry_count != count(e.entry_id))"
    ).fetchone()[0]:
        raise ValidationFailedError("outcome entry count differs from its entry rows")

    metadata_conflicts = con.execute(
        "SELECT count(*) FROM cohort_accessions c JOIN parent_accessions p USING(accession) "
        "WHERE c.form IS DISTINCT FROM p.form OR c.filing_date IS DISTINCT FROM p.filing_date "
        "OR c.report_date IS DISTINCT FROM p.report_date"
    ).fetchone()[0]
    if metadata_conflicts:
        raise ValidationFailedError(
            "cohort metadata conflicts with the current snapshot"
        )
    if con.execute(
        "SELECT count(*) FROM cohort_sources s LEFT JOIN parent_accessions p USING(accession) "
        "LEFT JOIN staged_outcomes o USING(accession) WHERE p.accession IS NULL AND o.accession IS NULL"
    ).fetchone()[0]:
        raise ValidationFailedError("cohort source edge has no accession facts")

    if refresh:
        con.execute(
            "CREATE TEMP TABLE delta_accessions AS SELECT c.accession, c.filing_cik, c.form, "
            "c.filing_date, c.report_date, o.bundle_url, o.bundle_size, c.index_url, "
            "o.page_sha256 AS index_sha256, coalesce(p.first_indexed_by, ?) AS first_indexed_by "
            "FROM cohort_accessions c JOIN eligible_outcomes o USING(accession) "
            "LEFT JOIN parent_accessions p USING(accession) WHERE o.status IN (?, ?) "
            "AND (p.accession IS NULL OR p.index_sha256 IS DISTINCT FROM o.page_sha256)",
            [source_identity, "parsed", "parsed_empty"],
        )
    else:
        con.execute(
            "CREATE TEMP TABLE delta_accessions AS SELECT c.accession, c.filing_cik, c.form, "
            "c.filing_date, c.report_date, o.bundle_url, o.bundle_size, c.index_url, "
            "o.page_sha256 AS index_sha256, coalesce(p.first_indexed_by, ?) AS first_indexed_by "
            "FROM cohort_accessions c JOIN eligible_outcomes o USING(accession) "
            "LEFT JOIN parent_accessions p USING(accession) WHERE o.status IN (?, ?)",
            [source_identity, "parsed", "parsed_empty"],
        )
    con.execute(
        "CREATE TEMP TABLE delta_entries AS SELECT e.* FROM candidate_entries e "
        "JOIN delta_accessions d USING(accession)"
    )
    con.execute(
        "CREATE TEMP TABLE delta_sources AS SELECT accession, source_cik, first_seen_by "
        "FROM new_sources"
    )
    con.execute(
        "CREATE TEMP TABLE delta_enumeration AS SELECT d.accession, o.vehicle, "
        "o.source_url, o.page_sha256 AS payload_sha256 FROM delta_accessions d "
        "JOIN staged_outcomes o USING(accession) WHERE o.vehicle IN (?, ?)",
        ["summary", "package"],
    )
    con.execute(
        "CREATE TEMP VIEW all_accessions AS SELECT accession, filing_cik, form, filing_date, "
        "report_date, bundle_url, bundle_size, index_url, index_sha256, first_indexed_by "
        "FROM parent_accessions p "
        "WHERE NOT EXISTS (SELECT 1 FROM delta_accessions d WHERE d.accession=p.accession) "
        "UNION ALL SELECT accession, filing_cik, form, filing_date, report_date, bundle_url, "
        "bundle_size, index_url, index_sha256, first_indexed_by FROM delta_accessions"
    )
    if refresh:
        con.execute(
            "CREATE TEMP VIEW all_entries AS SELECT entry_id, accession, table_kind, row_ordinal, "
            "sequence, document_type, document_label, description, filename, href, archive_url, byte_size "
            "FROM parent_entries p WHERE NOT EXISTS (SELECT 1 FROM delta_accessions d "
            "WHERE d.accession=p.accession) UNION ALL SELECT * FROM delta_entries"
        )
    else:
        con.execute(
            "CREATE TEMP VIEW all_entries AS SELECT entry_id, accession, table_kind, row_ordinal, "
            "sequence, document_type, document_label, description, filename, href, archive_url, byte_size "
            "FROM parent_entries UNION ALL SELECT * FROM delta_entries"
        )
    con.execute(
        "CREATE TEMP VIEW all_accession_sources AS SELECT accession, source_cik, first_seen_by "
        "FROM parent_accession_sources UNION ALL SELECT accession, source_cik, first_seen_by "
        "FROM delta_sources"
    )
