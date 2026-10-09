"""Read bounded, immutable inventory evidence for catalog-scoped accessions."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pyarrow.parquet as pq

from edgar_sec.foundation.hashing import file_sha256, sha256_text
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.manifest import PartDescriptor
from edgar_sec.infra.storage.dag.query import compile_pruned_views
from edgar_sec.infra.storage.dag.spec import RelationSpec
from edgar_sec.infra.storage.dag.traversal import LineageChain
from edgar_sec.infra.storage.duckdb import connect, sql_identifier

_BATCH_SIZE = 512


class InventoryPathsContract(Protocol):
    @property
    def snapshots_root(self) -> Path: ...


class InventoryEvidenceError(ValueError):
    """Raised when a pinned inventory snapshot cannot safely supply evidence."""


@dataclass(frozen=True, slots=True)
class CatalogAccessionScopeRow:
    accession: str
    form: str
    filing_date: str


@dataclass(frozen=True, slots=True)
class InventoryEvidenceRow:
    accession: str
    catalog_form: str
    catalog_filing_date: str
    indexed: bool
    accession_row: Mapping[str, Any] | None
    entry_row: Mapping[str, Any] | None


@dataclass(frozen=True, slots=True)
class InventoryEvidenceSource:
    paths: InventoryPathsContract
    snapshot_id: str
    snapshot_digest: str
    lineage: LineageChain
    _specs: tuple[RelationSpec, RelationSpec]
    _accession_columns: tuple[str, ...]
    _entry_columns: tuple[str, ...]

    def stream(
        self,
        accessions: Iterable[CatalogAccessionScopeRow],
        *,
        batch_size: int = _BATCH_SIZE,
    ) -> Iterator[InventoryEvidenceRow]:
        """Yield one row per active entry, or one row for either absence state."""
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        con = connect()
        try:
            con.execute(
                "CREATE TEMP TABLE requested_scope "
                "(accession VARCHAR, form VARCHAR, filing_date VARCHAR)"
            )
            scope_iter = iter(accessions)
            previous_accession: str | None = None
            while batch := _take_batch(scope_iter, batch_size):
                for scope in batch:
                    if not scope.accession or not scope.form or not scope.filing_date:
                        raise InventoryEvidenceError(
                            "catalog accession facts are incomplete"
                        )
                    if (
                        previous_accession is not None
                        and scope.accession <= previous_accession
                    ):
                        raise InventoryEvidenceError(
                            "catalog accessions must be unique and sorted"
                        )
                    previous_accession = scope.accession

                con.execute("DELETE FROM requested_scope")
                con.executemany(
                    "INSERT INTO requested_scope VALUES (?, ?, ?)",
                    [(row.accession, row.form, row.filing_date) for row in batch],
                )
                lower, upper = batch[0].accession, batch[-1].accession
                compile_pruned_views(
                    con,
                    self._specs,
                    self.lineage,
                    self.paths.snapshots_root,
                    {spec.name: (lower, upper) for spec in self._specs},
                )
                yield from self._read_batch(con, batch_size)
        finally:
            con.close()

    def _read_batch(self, con: Any, batch_size: int) -> Iterator[InventoryEvidenceRow]:
        accession_select = ", ".join(
            f"a.{sql_identifier(name)} AS {sql_identifier('_a_' + name)}"
            for name in self._accession_columns
        )
        entry_select = ", ".join(
            f"e.{sql_identifier(name)} AS {sql_identifier('_e_' + name)}"
            for name in self._entry_columns
        )
        query = (
            "SELECT s.accession, s.form, s.filing_date, "
            f"{accession_select}, {entry_select} "
            "FROM requested_scope s "
            "LEFT JOIN active_accessions a USING (accession) "
            "LEFT JOIN active_entries e USING (accession) "
            "ORDER BY s.accession, e.row_ordinal, e.table_kind, e.entry_id"
        )
        cursor = con.execute(query)
        accession_width = len(self._accession_columns)
        entry_start = 3 + accession_width
        while rows := cursor.fetchmany(batch_size):
            for values in rows:
                accession, form, filing_date = values[:3]
                raw_accession = values[3:entry_start]
                raw_entry = values[entry_start:]
                indexed = raw_accession[0] is not None
                if indexed:
                    accession_row = dict(zip(self._accession_columns, raw_accession))
                    if (
                        accession_row["form"] != form
                        or accession_row["filing_date"] != filing_date
                    ):
                        raise InventoryEvidenceError(
                            f"inventory facts disagree with catalog for {accession}"
                        )
                    entry_row = (
                        dict(zip(self._entry_columns, raw_entry))
                        if raw_entry[0] is not None
                        else None
                    )
                else:
                    accession_row = None
                    entry_row = None
                yield InventoryEvidenceRow(
                    accession=accession,
                    catalog_form=form,
                    catalog_filing_date=filing_date,
                    indexed=indexed,
                    accession_row=accession_row,
                    entry_row=entry_row,
                )


def _take_batch(
    source: Iterator[CatalogAccessionScopeRow], size: int
) -> list[CatalogAccessionScopeRow]:
    batch: list[CatalogAccessionScopeRow] = []
    for _ in range(size):
        try:
            batch.append(next(source))
        except StopIteration:
            break
    return batch


def _part_path(root: Path, owner_id: str, descriptor: PartDescriptor) -> Path:
    relative = Path(descriptor.path)
    if relative.is_absolute() or ".." in relative.parts:
        raise InventoryEvidenceError("snapshot part path escapes its owner")
    owner_root = (root / owner_id).resolve()
    direct = (owner_root / relative).resolve()
    shared = (root / relative).resolve()
    path = direct if direct.is_file() else shared if shared.is_file() else direct
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise InventoryEvidenceError("snapshot part path escapes its root") from exc
    return path


def _evidence_specs(
    relation_specs: Sequence[RelationSpec],
) -> tuple[RelationSpec, RelationSpec]:
    by_name = {spec.name: spec for spec in relation_specs}
    try:
        return by_name["accessions"], by_name["entries"]
    except KeyError as exc:
        raise InventoryEvidenceError(
            "inventory relation contracts are incomplete"
        ) from exc


def _validate_snapshot(
    paths: InventoryPathsContract,
    snapshot_id: str,
    evidence_specs: tuple[RelationSpec, RelationSpec],
) -> tuple[LineageChain, str]:
    catalog = DAGCatalog(paths.snapshots_root, read_only=True)
    if not catalog.has_snapshot(snapshot_id):
        raise InventoryEvidenceError(f"inventory snapshot is missing: {snapshot_id}")
    if catalog.audit_graph().get("cycles"):
        raise InventoryEvidenceError("inventory snapshot catalog contains a cycle")
    nodes = catalog.walk_lineage(snapshot_id)
    if not nodes:
        raise InventoryEvidenceError("inventory snapshot lineage is empty")
    for node in nodes:
        if node.kind != "checkpoint" and not node.parents:
            raise InventoryEvidenceError(
                f"inventory delta has no parent: {node.snapshot_id}"
            )
        for parent in node.parents:
            parent_digest = catalog.get_manifest_sha256(parent.snapshot_id)
            if parent_digest is None or (
                parent.manifest_sha256 and parent.manifest_sha256 != parent_digest
            ):
                raise InventoryEvidenceError(
                    f"inventory parent digest mismatch: {parent.snapshot_id}"
                )
    lineage = LineageChain(
        tip_id=snapshot_id,
        checkpoint_anchor_id=nodes[0].snapshot_id,
        nodes=tuple(nodes),
    )
    if lineage.tip_id != snapshot_id:
        raise InventoryEvidenceError("inventory lineage tip does not match its pin")

    digest = hashlib.sha256()
    digest.update(canonical_json({"snapshot_id": snapshot_id}).encode("utf-8"))
    relation_schemas = {spec.name: spec.schema for spec in evidence_specs}
    for node in lineage.nodes:
        catalog_digest = catalog.get_manifest_sha256(node.snapshot_id)
        calculated_digest = sha256_text(canonical_json(node.to_dict()))
        if catalog_digest is None or catalog_digest != calculated_digest:
            raise InventoryEvidenceError(
                f"inventory manifest digest mismatch: {node.snapshot_id}"
            )
        digest.update(
            canonical_json(
                {"snapshot_id": node.snapshot_id, "manifest_sha256": catalog_digest}
            ).encode("utf-8")
        )
        for relation_name, schema in relation_schemas.items():
            for part in node.relations.get(relation_name, ()):
                path = _part_path(paths.snapshots_root, node.snapshot_id, part)
                if not path.is_file():
                    raise InventoryEvidenceError(
                        f"snapshot part is missing: {part.path}"
                    )
                if (
                    path.stat().st_size != part.byte_size
                    or file_sha256(path) != part.sha256
                ):
                    raise InventoryEvidenceError(
                        f"snapshot part validation failed: {part.path}"
                    )
                try:
                    parquet = pq.ParquetFile(path)
                    valid_schema = parquet.schema_arrow.equals(
                        schema, check_metadata=False
                    )
                    valid_rows = parquet.metadata.num_rows == part.row_count
                except Exception as exc:
                    raise InventoryEvidenceError(
                        f"snapshot part validation failed: {part.path}"
                    ) from exc
                if not valid_schema or not valid_rows:
                    raise InventoryEvidenceError(
                        f"snapshot part validation failed: {part.path}"
                    )
                digest.update(
                    canonical_json(
                        {
                            "snapshot_id": node.snapshot_id,
                            "relation": relation_name,
                            **part.to_dict(),
                        }
                    ).encode("utf-8")
                )
    return lineage, digest.hexdigest()


def open_inventory_evidence(
    paths: InventoryPathsContract,
    snapshot_id: str,
    relation_specs: Sequence[RelationSpec],
) -> InventoryEvidenceSource:
    """Pass ``InventoryPaths`` and ``INVENTORY_RELATIONS`` to pin a named snapshot."""
    if not snapshot_id or snapshot_id == "current":
        raise InventoryEvidenceError("inventory evidence requires a named snapshot ID")
    evidence_specs = _evidence_specs(relation_specs)
    lineage, snapshot_digest = _validate_snapshot(paths, snapshot_id, evidence_specs)
    return InventoryEvidenceSource(
        paths=paths,
        snapshot_id=snapshot_id,
        snapshot_digest=snapshot_digest,
        lineage=lineage,
        _specs=evidence_specs,
        _accession_columns=tuple(evidence_specs[0].schema.names),
        _entry_columns=tuple(evidence_specs[1].schema.names),
    )


__all__ = [
    "CatalogAccessionScopeRow",
    "InventoryEvidenceError",
    "InventoryEvidenceRow",
    "InventoryEvidenceSource",
    "open_inventory_evidence",
]
