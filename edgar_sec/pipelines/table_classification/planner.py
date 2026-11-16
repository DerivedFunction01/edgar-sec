"""Deterministic plan construction against generic registry inputs.

The planner consumes rows the CLI translator emits from the registry;
it never imports the registry itself, so planning stays generic.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.serialization import canonical_hash, canonical_json
from edgar_sec.infra.storage.atomic import atomic_write_text
from edgar_sec.infra.storage.parquet import read_parquet_table, write_parquet_table

from .paths import ClassificationPaths
from .schemas import (
    GEOMETRY_EXPECTATIONS,
    PLAN_FORMAT_VERSION,
    PLAN_RELATION_SCHEMAS,
    PROVENANCE_ROUTES,
)

__all__ = [
    "DocumentTargetRow",
    "FilingRow",
    "Plan",
    "PlanError",
    "PlanRequest",
    "PlanResult",
    "ProfileApplicationRow",
    "WorkItem",
    "build_plan",
    "read_plan",
    "work_item_id_for",
]


class PlanError(RuntimeError):
    """A classification plan cannot be built from the supplied rows."""


@dataclass(frozen=True, slots=True)
class FilingRow:
    """One filing in the plan's filing set."""

    accession: str
    cik: int | None
    form: str
    filing_date: str | None = None
    stratum: str | None = None


@dataclass(frozen=True, slots=True)
class ProfileApplicationRow:
    """One generic profile application row for one filing."""

    accession: str
    family: str
    kind: str
    vocabulary_seat: str


@dataclass(frozen=True, slots=True)
class DocumentTargetRow:
    """One document target in planning's role/type/optional shape."""

    accession: str
    target_role: str
    target_type: str
    optional: bool
    document_name: str | None = None
    geometry_expectation: str = "expected"
    provenance_route: str = "render_to_txt"


@dataclass(frozen=True, slots=True)
class WorkItem:
    """One unit of run work: exactly one filing."""

    work_item_id: str
    accession: str
    ordinal: int


@dataclass(frozen=True, slots=True)
class PlanRequest:
    """Everything that defines one classification plan."""

    registry_state: str
    source_snapshot_id: str
    normalize_version: str
    renderer_version: str
    filings: tuple[FilingRow, ...]
    profile_application: tuple[ProfileApplicationRow, ...] = ()
    document_targets: tuple[DocumentTargetRow, ...] = ()
    created_at: str | None = None


@dataclass(frozen=True, slots=True)
class PlanResult:
    """Identity and location of one built plan bundle."""

    plan_id: str
    root: Path
    reused: bool


@dataclass(frozen=True, slots=True)
class Plan:
    """One loaded plan bundle: provenance plus its relations."""

    plan_id: str
    root: Path
    provenance: dict
    filings: tuple[FilingRow, ...]
    profile_application: tuple[ProfileApplicationRow, ...]
    document_targets: tuple[DocumentTargetRow, ...]
    work_items: tuple[WorkItem, ...]

    def filing_for(self, accession: str) -> FilingRow | None:
        """The filing row for one accession, if planned."""
        for filing in self.filings:
            if filing.accession == accession:
                return filing
        return None

    def targets_for(self, accession: str) -> tuple[DocumentTargetRow, ...]:
        """The document targets declared for one accession."""
        return tuple(
            target for target in self.document_targets if target.accession == accession
        )

    def profiles_for(self, accession: str) -> tuple[ProfileApplicationRow, ...]:
        """The profile application rows declared for one accession."""
        return tuple(
            row for row in self.profile_application if row.accession == accession
        )


def work_item_id_for(plan_id: str, accession: str) -> str:
    """The deterministic work-item id for one filing in one plan."""
    digest = hashlib.sha256(f"{plan_id}:{accession}".encode()).hexdigest()
    return f"wi-{digest[:16]}"


def _validate(request: PlanRequest) -> None:
    if not request.filings:
        raise PlanError("a plan needs at least one filing")
    accessions = [filing.accession for filing in request.filings]
    if len(set(accessions)) != len(accessions):
        raise PlanError("filing accessions must be unique")
    known = set(accessions)
    for row in request.profile_application:
        if row.accession not in known:
            raise PlanError(f"profile application for unplanned {row.accession}")
    seen_profiles: set[tuple[str, str]] = set()
    for row in request.profile_application:
        key = (row.accession, row.family)
        if key in seen_profiles:
            raise PlanError(f"duplicate profile application {key}")
        seen_profiles.add(key)
    seen_targets: set[tuple[str, str, str, str | None]] = set()
    for target in request.document_targets:
        if target.accession not in known:
            raise PlanError(f"document target for unplanned {target.accession}")
        if not target.target_role or not target.target_type:
            raise PlanError("document targets need a role and a type")
        if target.geometry_expectation not in GEOMETRY_EXPECTATIONS:
            raise PlanError(f"bad geometry expectation {target.geometry_expectation}")
        if target.provenance_route not in PROVENANCE_ROUTES:
            raise PlanError(f"bad provenance route {target.provenance_route}")
        key = (
            target.accession,
            target.target_role,
            target.target_type,
            target.document_name,
        )
        if key in seen_targets:
            raise PlanError(f"duplicate document target {key}")
        seen_targets.add(key)


def _sorted_rows(request: PlanRequest) -> dict[str, list[dict]]:
    filings = sorted(request.filings, key=lambda row: row.accession)
    profiles = sorted(
        request.profile_application, key=lambda row: (row.accession, row.family)
    )
    targets = sorted(
        request.document_targets,
        key=lambda row: (
            row.accession,
            row.target_role,
            row.target_type,
            row.document_name or "",
        ),
    )
    return {
        "filings": [
            {
                "accession": row.accession,
                "cik": row.cik,
                "form": row.form,
                "filing_date": row.filing_date,
                "stratum": row.stratum,
            }
            for row in filings
        ],
        "profile_application": [
            {
                "accession": row.accession,
                "family": row.family,
                "kind": row.kind,
                "vocabulary_seat": row.vocabulary_seat,
            }
            for row in profiles
        ],
        "document_targets": [
            {
                "accession": row.accession,
                "target_role": row.target_role,
                "target_type": row.target_type,
                "optional": row.optional,
                "document_name": row.document_name,
                "geometry_expectation": row.geometry_expectation,
                "provenance_route": row.provenance_route,
            }
            for row in targets
        ],
    }


def build_plan(request: PlanRequest, paths: ClassificationPaths) -> PlanResult:
    """Build one immutable plan bundle, or reuse the identical plan."""
    _validate(request)
    rows = _sorted_rows(request)
    header = {
        "plan_format_version": PLAN_FORMAT_VERSION,
        "registry_state": request.registry_state,
        "source_snapshot_id": request.source_snapshot_id,
        "normalize_version": request.normalize_version,
        "renderer_version": request.renderer_version,
    }
    identity = canonical_hash({"header": header, "relations": rows})
    plan_id = f"tcplan-{identity[:16]}"
    root = paths.plan_dir(plan_id)
    if root.is_dir() and paths.plan_manifest_path(plan_id).is_file():
        return PlanResult(plan_id=plan_id, root=root, reused=True)
    filings = rows["filings"]
    work_items = [
        {
            "work_item_id": work_item_id_for(plan_id, row["accession"]),
            "accession": row["accession"],
            "ordinal": ordinal,
        }
        for ordinal, row in enumerate(filings)
    ]
    provenance = {
        **header,
        "plan_id": plan_id,
        "created_at": request.created_at
        or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "filing_count": len(filings),
        "profile_count": len(rows["profile_application"]),
        "target_count": len(rows["document_targets"]),
        "work_item_count": len(work_items),
    }
    tables = {
        "provenance": pa.table(
            {
                name: [provenance[name]]
                for name in PLAN_RELATION_SCHEMAS["provenance"].names
            },
            schema=PLAN_RELATION_SCHEMAS["provenance"],
        ),
        "filings": pa.table(
            {
                name: [row[name] for row in filings]
                for name in PLAN_RELATION_SCHEMAS["filings"].names
            },
            schema=PLAN_RELATION_SCHEMAS["filings"],
        ),
        "profile_application": pa.table(
            {
                name: [row[name] for row in rows["profile_application"]]
                for name in PLAN_RELATION_SCHEMAS["profile_application"].names
            },
            schema=PLAN_RELATION_SCHEMAS["profile_application"],
        ),
        "document_targets": pa.table(
            {
                name: [row[name] for row in rows["document_targets"]]
                for name in PLAN_RELATION_SCHEMAS["document_targets"].names
            },
            schema=PLAN_RELATION_SCHEMAS["document_targets"],
        ),
        "work_items": pa.table(
            {
                name: [row[name] for row in work_items]
                for name in PLAN_RELATION_SCHEMAS["work_items"].names
            },
            schema=PLAN_RELATION_SCHEMAS["work_items"],
        ),
    }
    root.mkdir(parents=True, exist_ok=True)
    digests: dict[str, dict] = {}
    for relation, table in tables.items():
        target = paths.plan_relation_path(plan_id, relation)
        write_parquet_table(table, target)
        digests[relation] = {"rows": table.num_rows, "sha256": file_sha256(target)}
    manifest = {"plan_id": plan_id, **header, "relations": digests}
    atomic_write_text(paths.plan_manifest_path(plan_id), canonical_json(manifest))
    return PlanResult(plan_id=plan_id, root=root, reused=False)


def read_plan(paths: ClassificationPaths, plan_id: str) -> Plan:
    """Load one plan bundle from its published directory."""
    root = paths.plan_dir(plan_id)
    if not root.is_dir():
        raise PlanError(f"no plan bundle at {root}")

    def rows_of(relation: str) -> list[dict]:
        return read_parquet_table(
            paths.plan_relation_path(plan_id, relation)
        ).to_pylist()

    provenance_rows = rows_of("provenance")
    if len(provenance_rows) != 1:
        raise PlanError("provenance must carry exactly one row")
    return Plan(
        plan_id=plan_id,
        root=root,
        provenance=provenance_rows[0],
        filings=tuple(
            FilingRow(
                accession=row["accession"],
                cik=row["cik"],
                form=row["form"],
                filing_date=row["filing_date"],
                stratum=row["stratum"],
            )
            for row in rows_of("filings")
        ),
        profile_application=tuple(
            ProfileApplicationRow(
                accession=row["accession"],
                family=row["family"],
                kind=row["kind"],
                vocabulary_seat=row["vocabulary_seat"],
            )
            for row in rows_of("profile_application")
        ),
        document_targets=tuple(
            DocumentTargetRow(
                accession=row["accession"],
                target_role=row["target_role"],
                target_type=row["target_type"],
                optional=bool(row["optional"]),
                document_name=row["document_name"],
                geometry_expectation=row["geometry_expectation"],
                provenance_route=row["provenance_route"],
            )
            for row in rows_of("document_targets")
        ),
        work_items=tuple(
            WorkItem(
                work_item_id=row["work_item_id"],
                accession=row["accession"],
                ordinal=int(row["ordinal"]),
            )
            for row in rows_of("work_items")
        ),
    )
