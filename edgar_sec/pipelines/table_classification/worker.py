"""Per-filing classification work over the acquisition snapshot.

One work item classifies one filing: normalize, resolve exhibits,
produce contexts once, then run the cascade and the assembly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pyarrow as pa

from edgar_sec.engine.document.page_markers.models import PageArtifactPolicy
from edgar_sec.engine.forms.exhibit_resolution import (
    ExhibitCandidateInput,
    resolve_exhibits,
)
from edgar_sec.engine.forms.normalize import normalize_document
from edgar_sec.engine.tables.extraction.assembly import assemble
from edgar_sec.engine.tables.extraction.classify import classify_filing
from edgar_sec.engine.tables.extraction.context_production import (
    DocumentInput,
    produce_contexts,
)
from edgar_sec.engine.tables.extraction.typed_rows import structure_table
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.parquet import write_parquet_table

from .paths import ClassificationPaths
from .planner import DocumentTargetRow, FilingRow, Plan, WorkItem
from .schemas import (
    OUTPUT_RELATION_SCHEMAS,
    ROUTE_RAW,
    ROUTE_RENDER_TO_TXT,
    ROUTE_RENDER_TO_XML,
    STATUS_CLASSIFIED,
    STATUS_NO_DOCUMENTS,
    STATUS_NO_GEOMETRIES,
)

__all__ = [
    "FilingOutputs",
    "FilingSource",
    "SnapshotFilingSource",
    "SourceDocumentPayload",
    "WorkResult",
    "classify_documents",
    "classify_products",
    "classify_work_item",
]

_PRIMARY_ROLE = "primary"
_SNAPSHOT_RELATIONS = (
    "logical_documents",
    "representations",
    "representation_inputs",
    "text_payloads",
    "binary_payloads",
)


@dataclass(frozen=True, slots=True)
class SourceDocumentPayload:
    """One acquired document's payload and its inventory identity."""

    document_name: str
    target_role: str
    target_type: str
    raw: bytes
    document_type: str | None = None


class FilingSource(Protocol):
    """Payload access for one filing, keyed by its planned targets."""

    def documents_for(
        self, accession: str, targets: tuple[DocumentTargetRow, ...]
    ) -> tuple[SourceDocumentPayload, ...]:
        """Every acquired payload for one accession, primary first."""
        ...


@dataclass(frozen=True, slots=True)
class FilingOutputs:
    """One filing's run outputs: record, geometry, classifications."""

    filing_record: dict
    geometry_rows: tuple[dict, ...]
    classification_rows: tuple[dict, ...]


@dataclass(frozen=True, slots=True)
class WorkResult:
    """Counts from one completed work item."""

    work_item_id: str
    accession: str
    status: str
    geometry_count: int
    classified_count: int


class SnapshotFilingSource:
    """Read-only payload access over the acquisition snapshot tip."""

    def __init__(self, artifacts_root: Path) -> None:
        self._root = artifacts_root / "document_acquisition" / "snapshots"
        self.snapshot_id: str | None = None
        self._con = None
        self._open()

    def _open(self) -> None:
        from edgar_sec.infra.storage.dag.catalog import DAGCatalog
        from edgar_sec.infra.storage.duckdb import (
            connect,
            sql_identifier,
            sql_path_list,
        )

        if not (self._root / "catalog.sqlite").is_file():
            return
        catalog = DAGCatalog(self._root, read_only=True)
        pointer = catalog.read_pointer("main")
        if not pointer:
            return
        tip = str(pointer["snapshot_id"])
        parts: dict[str, tuple[Path, ...]] = {}
        for relation in _SNAPSHOT_RELATIONS:
            try:
                parts[relation] = catalog.resolve_active_relation(
                    tip, relation, verify_digests=False
                )
            except ValueError:
                parts[relation] = ()
        if not parts["logical_documents"]:
            return
        self.snapshot_id = tip
        self._con = connect()
        for relation, paths in parts.items():
            view = sql_identifier(relation)
            if paths:
                listing = sql_path_list([str(path) for path in paths])
                self._con.execute(
                    f"CREATE OR REPLACE VIEW {view} AS "
                    f"SELECT * FROM read_parquet({listing})"
                )
            else:
                self._con.execute(
                    f"CREATE OR REPLACE VIEW {view} AS "
                    "SELECT NULL::VARCHAR AS payload_sha256 WHERE FALSE"
                )

    @property
    def available(self) -> bool:
        """Whether a snapshot tip with documents was opened."""
        return self._con is not None

    def documents_for(
        self, accession: str, targets: tuple[DocumentTargetRow, ...]
    ) -> tuple[SourceDocumentPayload, ...]:
        """Every acquired payload for one accession, primary first."""
        if self._con is None:
            return ()
        rows = self._con.execute(
            "SELECT DISTINCT ld.logical_document_id, ld.planned_source_key, "
            "ld.target_role, ld.target_type, ri.payload_sha256 "
            "FROM logical_documents ld "
            "JOIN representations r "
            "ON r.logical_document_id = ld.logical_document_id "
            "JOIN representation_inputs ri "
            "ON ri.representation_id = r.representation_id "
            "WHERE ld.accession = ? ORDER BY ld.logical_document_id",
            [accession],
        ).fetchall()
        payloads: list[SourceDocumentPayload] = []
        seen: set[str] = set()
        for logical_id, source_key, role, target_type, sha in rows:
            if str(sha) in seen:
                continue
            raw = self._payload_bytes(str(sha))
            if raw is None:
                continue
            seen.add(str(sha))
            payloads.append(
                SourceDocumentPayload(
                    document_name=str(source_key or logical_id),
                    target_role=str(role),
                    target_type=str(target_type),
                    raw=raw,
                    document_type=str(target_type) if role != _PRIMARY_ROLE else None,
                )
            )
        payloads.sort(key=lambda payload: payload.target_role != _PRIMARY_ROLE)
        return tuple(payloads)

    def _payload_bytes(self, payload_sha256: str) -> bytes | None:
        row = self._con.execute(
            "SELECT payload_bytes FROM text_payloads "
            "WHERE payload_sha256 = ? "
            "UNION ALL "
            "SELECT payload_bytes FROM binary_payloads "
            "WHERE payload_sha256 = ? LIMIT 1",
            [payload_sha256, payload_sha256],
        ).fetchone()
        if row is not None and row[0] is not None:
            return bytes(row[0])
        return None

    def close(self) -> None:
        """Close the snapshot connection, if one was opened."""
        if self._con is not None:
            self._con.close()
            self._con = None


def _route_for(representation: str) -> str:
    """The render operation actually applied for a produced document."""
    if representation == "xml":
        return ROUTE_RENDER_TO_XML
    if representation == "html":
        return ROUTE_RENDER_TO_TXT
    return ROUTE_RAW


def classify_documents(
    plan: Plan,
    filing: FilingRow,
    targets: tuple[DocumentTargetRow, ...],
    payloads: tuple[SourceDocumentPayload, ...],
) -> FilingOutputs:
    """Classify one filing's payloads into run-output rows."""
    provenance = plan.provenance
    primary_payloads = [p for p in payloads if p.target_role == _PRIMARY_ROLE]
    absence: str | None = None
    documents: list[DocumentInput] = []
    routes: dict[str, str] = {}
    primary_text: str | None = None
    if not primary_payloads:
        absence = "not_in_snapshot"
    else:
        try:
            primary = normalize_document(
                primary_payloads[0].raw,
                form=filing.form,
                document_path=primary_payloads[0].document_name,
                page_policy=PageArtifactPolicy.ANNOTATE,
            )
            primary_text = primary.text
            documents.append(DocumentInput("primary", primary))
            routes["primary"] = _route_for(primary.representation)
        except ValueError:
            absence = "primary_unreadable"
    if documents and filing.stratum is not None:
        exhibit_payloads = [p for p in payloads if p.target_role != _PRIMARY_ROLE]
        normalized: dict[str, object] = {}
        candidates: list[ExhibitCandidateInput] = []
        for payload in exhibit_payloads:
            try:
                result = normalize_document(
                    payload.raw,
                    form=filing.form,
                    document_path=payload.document_name,
                    page_policy=PageArtifactPolicy.ANNOTATE,
                )
            except ValueError:
                continue
            normalized[payload.document_name] = result
            candidates.append(
                ExhibitCandidateInput(
                    document_type=payload.document_type or payload.target_type,
                    document_name=payload.document_name,
                    body_text=result.text,
                )
            )
        resolved = resolve_exhibits(
            tuple(candidates),
            stratum=filing.stratum,
            filing_form=filing.form,
            primary_text=primary_text,
        )
        for entry in resolved:
            if entry.body_confirmed and entry.document_name in normalized:
                result = normalized[entry.document_name]
                documents.append(DocumentInput(entry.document_name, result))
                routes[entry.document_name] = _route_for(result.representation)
    return _classify_produced(
        plan, filing, tuple(documents), routes, absence, provenance
    )


def _produced_rows(
    plan: Plan,
    filing: FilingRow,
    documents: tuple[DocumentInput, ...],
    routes: dict[str, str],
) -> tuple[list[dict], list[dict]]:
    geometry_rows: list[dict] = []
    classification_rows: list[dict] = []
    production = produce_contexts(documents)
    contexts = production.contexts
    if not contexts:
        return geometry_rows, classification_rows
    tables = [structure_table(context) for context in contexts]
    classifications, _scores = classify_filing(tables)
    assembly = assemble(list(contexts))
    assigned = {entry.table_index: entry for entry in assembly.assignments}
    for context, result in zip(contexts, classifications, strict=True):
        source = context.source_document or "primary"
        geometry_rows.append(
            {
                "plan_id": plan.plan_id,
                "accession": filing.accession,
                "source_document": source,
                "table_index": int(context.table_index),
                "provenance_route": routes.get(source, ROUTE_RAW),
            }
        )
        entry = assigned.get(int(context.table_index))
        classification_rows.append(
            {
                "plan_id": plan.plan_id,
                "accession": filing.accession,
                "source_document": source,
                "table_index": int(context.table_index),
                "family": result.family,
                "flavor": result.flavor,
                "kind": result.kind.value,
                "tier": result.tier,
                "score": float(result.score),
                "assembled_family": entry.family if entry else None,
                "mechanism": entry.mechanism if entry else None,
                "evidence": canonical_json(
                    [
                        {
                            "group": item.group,
                            "detail": item.detail,
                            "points": item.points,
                        }
                        for item in result.evidence
                    ]
                ),
            }
        )
    return geometry_rows, classification_rows


def _classify_produced(
    plan: Plan,
    filing: FilingRow,
    documents: tuple[DocumentInput, ...],
    routes: dict[str, str],
    absence: str | None,
    provenance: dict,
) -> FilingOutputs:
    geometry_rows: list[dict] = []
    classification_rows: list[dict] = []
    if documents:
        geometry_rows, classification_rows = _produced_rows(
            plan, filing, documents, routes
        )
    if not documents:
        status = STATUS_NO_DOCUMENTS
    elif not geometry_rows:
        status = STATUS_NO_GEOMETRIES
        absence = "no_geometries"
    else:
        status = STATUS_CLASSIFIED
        absence = None
    record = {
        "plan_id": plan.plan_id,
        "accession": filing.accession,
        "cik": filing.cik,
        "form": filing.form,
        "filing_date": filing.filing_date,
        "stratum": filing.stratum,
        "source_snapshot_id": provenance["source_snapshot_id"],
        "registry_state": provenance["registry_state"],
        "normalize_version": provenance["normalize_version"],
        "renderer_version": provenance["renderer_version"],
        "document_count": len(documents),
        "geometry_count": len(geometry_rows),
        "classified_count": len(classification_rows),
        "status": status,
        "absence_reason": absence,
    }
    return FilingOutputs(
        filing_record=record,
        geometry_rows=tuple(geometry_rows),
        classification_rows=tuple(classification_rows),
    )


def classify_products(
    plan: Plan,
    filing: FilingRow,
    documents: tuple[DocumentInput, ...],
    routes: dict[str, str] | None = None,
) -> FilingOutputs:
    """Classify one filing from produced documents, never re-normalizing.

    The products-side entry: callers holding stored normalization
    products (fixtures, review) pass DocumentInputs directly.
    """
    if routes is None:
        routes = {
            document.source_document: _route_for(document.result.representation)
            for document in documents
        }
    absence = None if documents else "no_products"
    return _classify_produced(plan, filing, documents, routes, absence, plan.provenance)


def _write_outputs(
    paths: ClassificationPaths, plan: Plan, item: WorkItem, outputs: FilingOutputs
) -> None:
    out_dir = paths.work_dir(plan.plan_id, item.work_item_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    tables = {
        "filing_records": (
            [outputs.filing_record],
            OUTPUT_RELATION_SCHEMAS["filing_records"],
        ),
        "geometry_inventory": (
            list(outputs.geometry_rows),
            OUTPUT_RELATION_SCHEMAS["geometry_inventory"],
        ),
        "classifications": (
            list(outputs.classification_rows),
            OUTPUT_RELATION_SCHEMAS["classifications"],
        ),
    }
    for relation, (rows, schema) in tables.items():
        table = pa.table(
            {name: [row[name] for row in rows] for name in schema.names},
            schema=schema,
        )
        write_parquet_table(table, out_dir / f"{relation}.parquet")


def classify_work_item(
    plan: Plan, item: WorkItem, source: FilingSource, paths: ClassificationPaths
) -> WorkResult:
    """Execute one work item and stage its output relations."""
    filing = plan.filing_for(item.accession)
    if filing is None:
        raise ValueError(f"work item for unplanned accession {item.accession}")
    targets = plan.targets_for(item.accession)
    payloads = source.documents_for(item.accession, targets)
    outputs = classify_documents(plan, filing, targets, payloads)
    _write_outputs(paths, plan, item, outputs)
    return WorkResult(
        work_item_id=item.work_item_id,
        accession=item.accession,
        status=outputs.filing_record["status"],
        geometry_count=len(outputs.geometry_rows),
        classified_count=len(outputs.classification_rows),
    )
