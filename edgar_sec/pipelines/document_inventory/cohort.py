"""Cohort projection and inventory-domain contracts for the document_inventory pipeline.

The catalog is a row-oriented input; the inventory boundary converts its string dates
and identities into validated values before grouping, then emits one work item per
accession. Shared immutable records live in `domain.document_inventory.models`.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.domain.document_inventory.models import (
    AccessionInventory,
    AccessionSource,
    CohortObservation,
    IndexWorkItem,
    InventoryCohort,
)
from edgar_sec.domain.filing_catalog.schemas import (
    TARGET_COLUMNS,
    TARGET_SCHEMA_VERSION,
)
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.domain.sec_urls import index_url_for
from edgar_sec.foundation.runtime.paths import DATA_FILE_NAME, PLAN_FILE_NAME
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.parquet import count_parquet_rows
from edgar_sec.pipelines.document_inventory.paths import (
    PLAN_TARGETS_DIR,
    form_partition_directory,
)

__all__ = [
    "CohortInputError",
    "project_cohort",
    "read_catalog_observations",
]


class CohortInputError(ValueError):
    """Validation failed while reading or projecting a cohort source.

    Reader errors carry the offending raw value; projection conflicts carry
    the affected accession.
    """

    code: str
    accession: AccessionNumber | None

    def __init__(
        self,
        code: str,
        accession: AccessionNumber | None = None,
        *,
        detail: str | None = None,
    ):
        message = _error_message(code, accession, detail=detail)
        super().__init__(message)
        self.code = code
        self.accession = accession


def _error_message(
    code: str, accession: AccessionNumber | None, *, detail: str | None
) -> str:
    if detail is not None:
        return f"{accession if accession else '?'}: {detail}"
    return {
        "invalid_bundle": "manifest or target part invalid",
        "invalid_identity": "invalid accession or CIK",
        "invalid_date": "invalid date",
        "missing_form": "form is missing",
        "conflicting_form": "conflicting forms",
        "conflicting_filing_date": "conflicting filing dates",
        "conflicting_report_date": "conflicting report dates",
    }[code]


def _parse_accession(raw: object) -> AccessionNumber | None:
    if raw is None or not isinstance(raw, str):
        return None
    try:
        return AccessionNumber.from_any(raw)
    except ValueError:
        return None


def _parse_cik(raw: object) -> Cik | None:
    if raw is None or not isinstance(raw, str):
        return None
    try:
        return Cik.from_raw(raw)
    except ValueError:
        return None


def _parse_date(raw: object, label: str) -> date | None:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise CohortInputError(
            "invalid_date", None, detail=f"{label} '{raw}' is not ISO-8601"
        )


def _row_to_observation(
    batch: pa.RecordBatch, index: int, cohort_source_id: str
) -> CohortObservation:
    accession = _parse_accession(batch.column("accession")[index].as_py())
    if accession is None:
        raw = batch.column("accession")[index].as_py()
        raise CohortInputError(
            "invalid_identity",
            None,
            detail=f"accession {raw!r} from {cohort_source_id}",
        )
    source_cik = _parse_cik(batch.column("source_cik")[index].as_py())
    if source_cik is None:
        raw = batch.column("source_cik")[index].as_py()
        raise CohortInputError(
            "invalid_identity",
            accession,
            detail=f"source_cik {raw!r} from {cohort_source_id}",
        )
    form = batch.column("form")[index].as_py()
    if form is None or (isinstance(form, str) and not form.strip()):
        raise CohortInputError(
            "missing_form", accession, detail=f"form is null from {cohort_source_id}"
        )
    filing_date = _parse_date(batch.column("filing_date")[index].as_py(), "filing")
    report_date = _parse_date(batch.column("report_date")[index].as_py(), "report")
    return CohortObservation(
        cohort_source_id, accession, source_cik, form, filing_date, report_date
    )


def _stream_part(part_path: Path, cohort_source_id: str) -> Iterator[CohortObservation]:
    schema = pq.read_schema(part_path)
    if not set(TARGET_COLUMNS).issubset(set(schema.names)):
        raise CohortInputError(
            "invalid_bundle",
            None,
            detail=f"part {part_path} is missing declared columns "
            f"{sorted(set(TARGET_COLUMNS) - set(schema.names))}",
        )
    pf = pq.ParquetFile(part_path)
    for batch in pf.iter_batches():
        for i in range(batch.num_rows):
            yield _row_to_observation(batch, i, cohort_source_id)


def read_catalog_observations(
    source_dir: Path | str,
    cohort_source_id: str,
    source_kind: str,
) -> Iterator[CohortObservation]:
    """Stream validated cohort observations from a filing_catalog snapshot or plan.

    ``source_kind`` is ``catalog_snapshot`` or ``catalog_plan``; the source-specific
    SQLite record or plan bundle is validated before the first row is yielded.
    """
    source_dir = Path(source_dir)
    if source_kind == "catalog_snapshot":
        parts, declared_count = _read_catalog_snapshot(source_dir)
    elif source_kind == "catalog_plan":
        parts, declared_count = _read_plan_manifest(source_dir)
    else:
        raise ValueError(f"unknown source_kind: {source_kind!r}")
    for part_path in parts:
        for obs in _stream_part(part_path, cohort_source_id):
            yield obs
    if (
        declared_count is not None
        and sum(count_parquet_rows(p) for p in parts) != declared_count
    ):
        raise CohortInputError(
            "invalid_bundle",
            None,
            detail=f"declared row count {declared_count} does not match "
            f"{sum(count_parquet_rows(p) for p in parts)} across parts",
        )


def _read_catalog_snapshot(source_dir: Path) -> tuple[list[Path], int]:
    try:
        catalog = DAGCatalog(source_dir.parent, read_only=True)
    except FileNotFoundError as exc:
        raise CohortInputError(
            "invalid_bundle", None, detail="snapshot DAG catalog is missing"
        ) from exc
    node = catalog.get_manifest(source_dir.name)
    if node is None:
        raise CohortInputError(
            "invalid_bundle", None, detail="snapshot is not present in the DAG catalog"
        )
    schema_version = node.schema_versions.get("filing_targets")
    if schema_version != TARGET_SCHEMA_VERSION:
        raise CohortInputError(
            "invalid_bundle",
            None,
            detail=(
                f"filing_targets schema version {schema_version!r} "
                f"!= {TARGET_SCHEMA_VERSION!r}"
            ),
        )
    descriptors = node.relations.get("filing_targets", ())
    if not descriptors:
        raise CohortInputError(
            "invalid_bundle", None, detail="catalog has no target parts"
        )
    declared_count = sum(part.row_count for part in descriptors)
    try:
        part_paths = catalog.resolve_relation(source_dir.name, "filing_targets")
    except ValueError as exc:
        raise CohortInputError("invalid_bundle", None, detail=str(exc)) from exc
    for part, resolved in zip(descriptors, part_paths, strict=True):
        actual_rows = count_parquet_rows(resolved)
        if actual_rows != part.row_count:
            raise CohortInputError(
                "invalid_bundle",
                None,
                detail=(
                    f"part {part.path} declares {part.row_count} rows but has "
                    f"{actual_rows}"
                ),
            )
    return list(part_paths), declared_count


def _read_plan_manifest(source_dir: Path) -> tuple[list[Path], int | None]:
    plan_path = source_dir / PLAN_FILE_NAME
    if not plan_path.is_file():
        raise CohortInputError(
            "invalid_bundle", None, detail=f"plan.json missing: {plan_path}"
        )
    payload = _read_json(plan_path)
    if not isinstance(payload, dict):
        raise CohortInputError(
            "invalid_bundle", None, detail="plan.json is not an object"
        )
    catalog_id = payload.get("catalog_id")
    scope = payload.get("scope")
    forms = payload.get("forms")
    if not isinstance(catalog_id, str):
        raise CohortInputError(
            "invalid_bundle", None, detail="plan catalog_id is invalid"
        )
    if scope not in {"deterministic", "policy"}:
        raise CohortInputError(
            "invalid_bundle", None, detail=f"plan scope {scope!r} is unknown"
        )
    if not isinstance(forms, list) or not forms:
        raise CohortInputError("invalid_bundle", None, detail="plan forms is empty")
    declared_count = 0
    part_paths: list[Path] = []
    targets = source_dir / PLAN_TARGETS_DIR
    if not targets.is_dir():
        raise CohortInputError(
            "invalid_bundle", None, detail="plan targets dir missing"
        )
    for form in sorted(forms):
        partition = form_partition_directory(form)
        part_path = targets / partition / DATA_FILE_NAME
        if not part_path.is_file():
            raise CohortInputError(
                "invalid_bundle",
                None,
                detail=f"form part missing: {partition}/{DATA_FILE_NAME}",
            )
        rows = count_parquet_rows(part_path)
        if payload.get("counts", {}).get(form) != rows:
            raise CohortInputError(
                "invalid_bundle",
                None,
                detail=f"form {partition} declares {payload.get('counts', {}).get(form)} rows but has {rows}",
            )
        declared_count += rows
        part_paths.append(part_path)
    return part_paths, declared_count


def _read_json(path: Path) -> object:
    import json

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def project_cohort(
    observations: Iterable[CohortObservation],
    *,
    archive_base_url: str,
) -> InventoryCohort:
    """Group observations by accession, validate filing facts, emit work items.

    Intended for selected cohorts and plan fragments, not the full snapshot.
    """
    obs_list = list(observations)
    by_accession: dict[AccessionNumber, list[CohortObservation]] = {}
    for obs in obs_list:
        by_accession.setdefault(obs.accession, []).append(obs)

    accessions: list[AccessionInventory] = []
    sources: list[AccessionSource] = []
    work_items: list[IndexWorkItem] = []

    for accession in sorted(by_accession, key=str):
        group = by_accession[accession]
        _validate_accession_group(group, accession)
        filing_cik = Cik.from_raw(accession.normalized[:10])
        dedup: dict[tuple[Cik, str], CohortObservation] = {}
        for obs in sorted(group, key=lambda o: (o.source_cik, o.cohort_source_id)):
            key = (obs.source_cik, obs.cohort_source_id)
            existing = dedup.get(key)
            if existing is None:
                dedup[key] = obs
            else:
                _raise_duplicate_conflict(existing, obs, accession)
        for (cik, srcid), obs in sorted(
            dedup.items(), key=lambda kv: (kv[0][0], kv[0][1])
        ):
            sources.append(AccessionSource(accession, cik, first_seen_by=srcid))
        source_ciks = tuple(sorted((k[0] for k in dedup.keys())))
        cohort_sources = tuple(sorted({o.cohort_source_id for o in group}))
        # report_date is nullable: prefer a present value if any (missing-vs-present is non-conflicting)
        report_date = next(
            (o.report_date for o in group if o.report_date is not None), None
        )
        first = group[0]
        accessions.append(
            AccessionInventory(
                accession,
                filing_cik,
                source_ciks,
                form=first.form,
                filing_date=first.filing_date,
                report_date=report_date,
                cohort_sources=cohort_sources,
            )
        )
        work_items.append(
            IndexWorkItem(
                accession,
                index_url_for(
                    accession,
                    source_ciks[0],
                    archive_base_url=archive_base_url,
                ),
            )
        )

    return InventoryCohort(
        observations=tuple(
            sorted(
                obs_list, key=lambda o: (o.accession, o.source_cik, o.cohort_source_id)
            )
        ),
        accessions=tuple(accessions),
        sources=tuple(sources),
        work_items=tuple(work_items),
    )


def _validate_accession_group(
    group: list[CohortObservation], accession: AccessionNumber
) -> None:
    forms = {o.form for o in group}
    if len(forms) > 1:
        raise CohortInputError("conflicting_form", accession, detail=f"{sorted(forms)}")
    filing_dates = {o.filing_date for o in group}
    if len(filing_dates) > 1:
        raise CohortInputError(
            "conflicting_filing_date", accession, detail=f"{sorted(filing_dates)}"
        )
    present_report = sorted({o.report_date for o in group if o.report_date is not None})
    if len(present_report) > 1:
        raise CohortInputError(
            "conflicting_report_date", accession, detail=f"{present_report}"
        )


def _raise_duplicate_conflict(
    existing: CohortObservation, obs: CohortObservation, accession: AccessionNumber
) -> None:
    """Report a duplicate observation unless it is byte-identical (collapse)."""
    if existing.form != obs.form:
        raise CohortInputError(
            "conflicting_form", accession, detail=f"{existing.form!r} vs {obs.form!r}"
        )
    if existing.filing_date != obs.filing_date:
        raise CohortInputError(
            "conflicting_filing_date",
            accession,
            detail=f"{existing.filing_date} vs {obs.filing_date}",
        )
    if existing.report_date != obs.report_date:
        raise CohortInputError(
            "conflicting_report_date",
            accession,
            detail=f"{existing.report_date} vs {obs.report_date}",
        )
    # Identical duplicate: collapse, no new source row.
