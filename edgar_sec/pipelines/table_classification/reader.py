"""Read-only access to the published classification store.

Reads resolve the branch tip through the DAG catalog and never write;
an absent store or filing answers as absence, with both snapshot ids.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq

from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.duckdb import connect, sql_identifier, sql_path_list

from .paths import ClassificationPaths
from .specs import STORE_RELATION_SPECS
from .store import store_tip

_SPEC_BY_NAME = {spec.name: spec for spec in STORE_RELATION_SPECS}


@dataclass(frozen=True, slots=True)
class StoreProvenance:
    """The provenance header of the store snapshot a read came from."""

    store_snapshot_id: str
    source_snapshot_id: str
    plan_id: str
    plan_format_version: str
    run_output_version: str
    registry_state: str
    normalize_version: str
    renderer_version: str
    merged_at: str
    published_at: str


@dataclass(frozen=True, slots=True)
class ClassifiedTableRow:
    """One classified geometry, joined to its inventory provenance."""

    accession: str
    source_document: str
    table_index: int
    provenance_route: str
    family: str
    flavor: str | None
    kind: str
    tier: str
    score: float
    assembled_family: str | None
    mechanism: str | None
    evidence: str


@dataclass(frozen=True, slots=True)
class ClassifiedTablesRead:
    """One filing's classified tables plus the store provenance."""

    provenance: StoreProvenance
    accession: str
    tables: tuple[ClassifiedTableRow, ...]


class ClassificationStoreReader:
    """Read-only reader over the classification store's branch tip."""

    def __init__(self, paths: ClassificationPaths, branch: str = "main") -> None:
        self._paths = paths
        self._branch = branch

    def tip_snapshot_id(self) -> str | None:
        """The tip store snapshot id, or ``None`` when unpublished."""
        return store_tip(self._paths, self._branch)

    def provenance(self) -> StoreProvenance | None:
        """The tip snapshot's provenance header, or ``None`` if absent."""
        tip = self.tip_snapshot_id()
        if tip is None:
            return None
        table = self._read_relation(tip, "run_provenance")
        if table is None or table.num_rows == 0:
            return None
        row = table.to_pylist()[0]
        return StoreProvenance(
            store_snapshot_id=str(row["store_snapshot_id"]),
            source_snapshot_id=str(row["source_snapshot_id"]),
            plan_id=str(row["plan_id"]),
            plan_format_version=str(row["plan_format_version"]),
            run_output_version=str(row["run_output_version"]),
            registry_state=str(row["registry_state"]),
            normalize_version=str(row["normalize_version"]),
            renderer_version=str(row["renderer_version"]),
            merged_at=str(row["merged_at"]),
            published_at=str(row["published_at"]),
        )

    def classified_tables(self, accession: str) -> ClassifiedTablesRead | None:
        """One filing's classified tables, or ``None`` when absent."""
        provenance = self.provenance()
        if provenance is None:
            return None
        tip = provenance.store_snapshot_id
        parts = {
            name: self._part_paths(tip, name)
            for name in ("classifications", "geometry_inventory")
        }
        if any(paths is None for paths in parts.values()):
            return None
        con = connect()
        try:
            for name, paths in parts.items():
                con.execute(
                    f"CREATE OR REPLACE VIEW {sql_identifier(name)} AS "
                    f"SELECT * FROM read_parquet({sql_path_list([str(p) for p in paths or ()])})"
                )
            rows = con.execute(
                "SELECT c.accession, c.source_document, c.table_index, "
                "g.provenance_route, c.family, c.flavor, c.kind, c.tier, "
                "c.score, c.assembled_family, c.mechanism, c.evidence "
                "FROM classifications c "
                "JOIN geometry_inventory g ON g.accession = c.accession "
                "AND g.source_document = c.source_document "
                "AND g.table_index = c.table_index "
                "WHERE c.accession = ? "
                "ORDER BY c.source_document, c.table_index",
                [accession],
            ).fetchall()
        finally:
            con.close()
        if not rows:
            return None
        return ClassifiedTablesRead(
            provenance=provenance,
            accession=accession,
            tables=tuple(
                ClassifiedTableRow(
                    accession=str(r[0]),
                    source_document=str(r[1]),
                    table_index=int(r[2]),
                    provenance_route=str(r[3]),
                    family=str(r[4]),
                    flavor=str(r[5]) if r[5] is not None else None,
                    kind=str(r[6]),
                    tier=str(r[7]),
                    score=float(r[8]),
                    assembled_family=str(r[9]) if r[9] is not None else None,
                    mechanism=str(r[10]) if r[10] is not None else None,
                    evidence=str(r[11]),
                )
                for r in rows
            ),
        )

    def filing_accessions(self) -> tuple[str, ...]:
        """Every accession the tip store carries, in accession order."""
        tip = self.tip_snapshot_id()
        if tip is None:
            return ()
        table = self._read_relation(tip, "filing_records")
        if table is None:
            return ()
        return tuple(str(value) for value in table.column("accession").to_pylist())

    def _part_paths(self, tip: str, relation: str) -> tuple[Path, ...] | None:
        catalog = DAGCatalog(self._paths.snapshots_root, read_only=True)
        try:
            return catalog.resolve_active_relation(
                tip, relation, relative_to=self._paths.snapshots_root
            )
        except ValueError:
            return None

    def _read_relation(self, tip: str, relation: str):  # noqa: ANN202
        """The tip's active table for one relation, or ``None``."""
        parts = self._part_paths(tip, relation)
        if not parts:
            return None
        return pq.read_table(
            [str(p) for p in parts], schema=_SPEC_BY_NAME[relation].schema
        )


__all__ = [
    "ClassifiedTableRow",
    "ClassifiedTablesRead",
    "ClassificationStoreReader",
    "StoreProvenance",
]
