"""Streaming reader for a published ``filing_catalog`` target-plan bundle.

The bundle is the selection authority: rows are validated, never re-selected. Validation
runs before the first fetch, and chunk identity follows from the plan and an ordinal
rather than from row arrival or filesystem order.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from edgar_sec.domain.document.models import (
    AccessionNumber,
    Cik,
    DocumentLocator,
    DocumentPathSource,
    FilingOccurrence,
)
from edgar_sec.domain.filing_catalog.schemas import (
    LOCATOR_BASE_COLUMNS,
    LOCATOR_POLICY_COLUMNS,
    SCOPE_DETERMINISTIC,
    SCOPE_POLICY,
    TARGET_COLUMNS,
)
from edgar_sec.foundation.hashing import sha256_text
from edgar_sec.infra.storage.duckdb import connect, sql_literal, sql_path_list
from edgar_sec.infra.storage.parquet import count_parquet_rows, read_parquet_schema
from edgar_sec.pipelines.filing_catalog.paths import (
    LOCATOR_GROUPS_NAME,
    PLAN_FILE_NAME,
    PLAN_TARGETS_DIR_NAME,
    form_partition_name,
)
from edgar_sec.pipelines.filing_catalog.publication import (
    TARGET_PLAN_SCHEMA_VERSION,
    plan_bundle_complete,
    plan_fingerprint_from_plan,
)
from edgar_sec.pipelines.document_storage.work_order import ChunkInput

#: Bumped when a change to what a chunk holds or how it is named would make previously
#: published chunk identities ambiguous.
WORK_ORDER_VERSION = "catalog-1"

SUPPORTED_PLAN_SCHEMA_VERSIONS = frozenset({TARGET_PLAN_SCHEMA_VERSION})

_SCOPE_LOCATOR_COLUMNS = {
    SCOPE_DETERMINISTIC: LOCATOR_BASE_COLUMNS,
    SCOPE_POLICY: LOCATOR_POLICY_COLUMNS,
}

_STREAM_BATCH_ROWS = 2048


class CatalogPlanError(RuntimeError):
    """A published plan bundle is unusable as an acquisition work order."""


@dataclass(frozen=True, slots=True)
class CatalogPlanMetadata:
    """The published identity of one plan bundle."""

    plan_id: str
    catalog_id: str
    scope: str
    selection_fingerprint: str
    locator_count: int = 0
    occurrence_count: int = 0


class CatalogPlan:
    """A validated plan bundle, readable as bounded chunks.

    Construction validates the bundle; each chunk is read on demand, so work in progress
    is bounded by chunk size rather than by plan size.
    """

    def __init__(
        self,
        plan_dir: str | Path,
        *,
        chunk_size: int,
        batch_rows: int = _STREAM_BATCH_ROWS,
    ) -> None:
        if chunk_size < 1:
            raise CatalogPlanError(f"chunk_size must be positive: {chunk_size}")
        self._plan_dir = Path(plan_dir).resolve()
        self._chunk_size = chunk_size
        self._batch_rows = batch_rows
        self._published = _read_plan_json(self._plan_dir)
        self._counts = _read_plan_counts(self._plan_dir)
        self._meta = _read_plan_metadata(self._plan_dir, self._counts)
        self._locator_path = self._plan_dir / LOCATOR_GROUPS_NAME
        self._target_paths = _target_partitions(self._plan_dir, self._counts)
        locator_count = _validate_bundle(
            self._plan_dir,
            self._meta,
            self._locator_path,
            self._target_paths,
            self._counts,
        )
        actual_fingerprint = plan_fingerprint_from_plan(self._plan_dir, self._published)
        if actual_fingerprint != self._meta.selection_fingerprint:
            raise CatalogPlanError(
                "plan bundle selection fingerprint does not match its locator groups"
            )
        self._meta = replace(self._meta, locator_count=locator_count)

    @property
    def metadata(self) -> CatalogPlanMetadata:
        """The published identity of the bundle this reader validates."""
        return self._meta

    @property
    def plan_dir(self) -> Path:
        return self._plan_dir

    @property
    def chunk_size(self) -> int:
        return self._chunk_size

    @property
    def canonical_metadata(self) -> dict[str, Any]:
        return {
            "plan_id": self._meta.plan_id,
            "catalog_id": self._meta.catalog_id,
            "scope": self._meta.scope,
            "selection_fingerprint": self._meta.selection_fingerprint,
            "counts": dict(sorted(self._counts.items())),
        }

    @property
    def source_files(self) -> tuple[Path, ...]:
        return (
            self._plan_dir / PLAN_FILE_NAME,
            self._locator_path,
            *self._target_paths,
        )

    @property
    def chunk_count(self) -> int:
        """Total chunks a full read yields, known once the locator count is."""
        return -(-self._meta.locator_count // self._chunk_size)

    def iter_chunks(self) -> Iterator[ChunkInput]:
        """Yield chunks of at most ``chunk_size`` locators, in stable plan order.

        Rows arrive grouped by locator key, so closing the previous group on the next key
        keeps every occurrence of one locator in the same chunk as its fetch.
        """
        ordinal = 0
        pending: list[DocumentLocator] = []
        occurrences: list[FilingOccurrence] = []
        group_key: str | None = None
        group_row: dict[str, Any] | None = None

        for row in self._iter_rows():
            key = str(row["document_locator_key"])
            if key != group_key:
                if group_row is not None:
                    pending.append(_locator_from_group(group_row, group_key))
                    if len(pending) >= self._chunk_size:
                        yield _chunk(self._meta.plan_id, ordinal, pending, occurrences)
                        ordinal += 1
                        pending, occurrences = [], []
                group_key, group_row = key, row
            occurrences.append(_occurrence_from_row(row))

        if group_row is not None:
            pending.append(_locator_from_group(group_row, group_key))
            yield _chunk(self._meta.plan_id, ordinal, pending, occurrences)

    def iter_locators(self) -> Iterator[DocumentLocator]:
        """Yield one locator per work item, in the order chunks are derived."""
        group_key: str | None = None
        group_row: dict[str, Any] | None = None
        for row in self._iter_rows():
            key = str(row["document_locator_key"])
            if key != group_key:
                if group_row is not None:
                    yield _locator_from_group(group_row, group_key)
                group_key, group_row = key, row
        if group_row is not None:
            yield _locator_from_group(group_row, group_key)

    def locators_by_key(self, keys: Iterable[str]) -> dict[str, DocumentLocator]:
        """Return only the named locators, stopping as soon as all are resolved."""
        wanted = {key for key in keys if key}
        found: dict[str, DocumentLocator] = {}
        if not wanted:
            return found
        for row in self._iter_rows():
            key = str(row["document_locator_key"])
            if key in wanted:
                found[key] = _locator_from_group(row, key)
                if len(found) == len(wanted):
                    break
        return found

    def _iter_rows(self) -> Iterator[dict[str, Any]]:
        """Stream this bundle's joined, key-ordered rows."""
        return _iter_rows(self._target_paths, self._locator_path, self._batch_rows)


def _read_plan_counts(plan_dir: Path) -> dict[str, int]:
    """Read the per-form target counts ``plan.json`` published."""
    published = _read_plan_json(plan_dir)
    counts = published.get("counts")
    if not isinstance(counts, dict) or not counts:
        raise CatalogPlanError(f"plan.json in {plan_dir} records no target counts")
    resolved: dict[str, int] = {}
    for form, count in counts.items():
        try:
            resolved[str(form)] = int(count)
        except (TypeError, ValueError) as exc:
            raise CatalogPlanError(
                f"plan.json in {plan_dir} records a non-numeric count for form {form!r}"
            ) from exc
    return resolved


def _read_plan_json(plan_dir: Path) -> dict[str, Any]:
    path = plan_dir / PLAN_FILE_NAME
    if not path.is_file():
        raise CatalogPlanError(f"plan.json not found: {path}")
    try:
        published = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogPlanError(f"unreadable plan.json at {path}: {exc}") from exc
    if not isinstance(published, dict):
        raise CatalogPlanError(f"plan.json at {path} is not an object")
    return published


def _read_plan_metadata(plan_dir: Path, counts: dict[str, int]) -> CatalogPlanMetadata:
    """Check the published ``plan.json`` identity this reader can execute."""
    published = _read_plan_json(plan_dir)
    version = str(published.get("plan_schema_version") or "")
    if version not in SUPPORTED_PLAN_SCHEMA_VERSIONS:
        raise CatalogPlanError(
            f"unsupported plan schema version {version!r}; this reader accepts "
            f"{sorted(SUPPORTED_PLAN_SCHEMA_VERSIONS)}"
        )
    plan_id = str(published.get("plan_id") or "")
    if not plan_id:
        raise CatalogPlanError(f"plan.json in {plan_dir} records no plan_id")
    if plan_id != plan_dir.name:
        raise CatalogPlanError(
            f"plan_id {plan_id!r} does not match bundle directory {plan_dir.name!r}"
        )
    scope = str(published.get("scope") or "")
    if scope not in _SCOPE_LOCATOR_COLUMNS:
        raise CatalogPlanError(f"unknown plan scope {scope!r}")
    return CatalogPlanMetadata(
        plan_id=plan_id,
        catalog_id=str(published.get("catalog_id") or ""),
        scope=scope,
        selection_fingerprint=str(published.get("plan_fingerprint") or ""),
        occurrence_count=sum(counts.values()),
    )


def _target_partitions(plan_dir: Path, counts: dict[str, int]) -> tuple[Path, ...]:
    """Resolve every active target partition, in sorted form order.

    ``reserve_targets.parquet`` holds locators withheld from the active set and is never
    resolved here.
    """
    paths: list[Path] = []
    for form in sorted(counts):
        data = (
            plan_dir
            / PLAN_TARGETS_DIR_NAME
            / f"form={form_partition_name(form)}"
            / "data.parquet"
        )
        if not data.is_file():
            raise CatalogPlanError(f"declared target partition is missing: {data}")
        paths.append(data)
    return tuple(paths)


def _validate_bundle(
    plan_dir: Path,
    meta: CatalogPlanMetadata,
    locator_path: Path,
    target_paths: tuple[Path, ...],
    counts: dict[str, int],
) -> int:
    """Reject an incomplete, mismatched, or lineage-inconsistent bundle before fetching.

    Returns the distinct locator count, which the chunk count needs and cannot be
    derived from occurrence counts.
    """
    if not plan_bundle_complete(plan_dir, meta.scope):
        raise CatalogPlanError(
            f"plan bundle at {plan_dir} is incomplete for scope {meta.scope!r}; "
            "remove it and rerun the catalog planner"
        )

    expected_locators = _SCOPE_LOCATOR_COLUMNS[meta.scope]
    actual_locators = read_parquet_schema(locator_path).names
    if tuple(actual_locators) != tuple(expected_locators):
        raise CatalogPlanError(
            f"locator group schema does not match {meta.scope} scope: expected "
            f"{list(expected_locators)}, got {actual_locators}"
        )
    # Policy targets widen with feature columns; storage projects the target columns by
    # name and ignores the rest, so a superset is expected rather than a mismatch.
    for path in target_paths:
        actual_targets = read_parquet_schema(path).names
        missing = [name for name in TARGET_COLUMNS if name not in actual_targets]
        if missing:
            raise CatalogPlanError(
                f"target partition {path.parent.name} is missing {missing}; "
                f"it publishes {actual_targets}"
            )

    _validate_counts(target_paths, counts)
    return _validate_lineage(locator_path, target_paths)


def _validate_counts(target_paths: tuple[Path, ...], counts: dict[str, int]) -> None:
    """Check each partition's rows against the count ``plan.json`` published for it."""
    by_partition = {
        f"form={form_partition_name(form)}": (form, declared)
        for form, declared in counts.items()
    }
    for path in target_paths:
        partition = path.parent.name
        if partition not in by_partition:
            raise CatalogPlanError(f"undeclared target partition: {partition}")
        _form, declared = by_partition[partition]
        actual = count_parquet_rows(path)
        if actual != declared:
            raise CatalogPlanError(
                f"target partition {partition} holds {actual} rows; "
                f"plan.json declares {declared}"
            )


def _validate_lineage(locator_path: Path, target_paths: tuple[Path, ...]) -> int:
    """Check that every target resolves to one locator group and agrees with it.

    Only fields the key implies are invariants; ``form`` and ``archive_url`` vary across
    co-filers of one document. Digests are recomputed in the catalog's SQL spelling.
    """
    targets = sql_path_list(str(path) for path in target_paths)
    locators = sql_literal(str(locator_path))
    with connect() as con:
        orphan_targets = _scalar(
            con,
            "SELECT count(*) FROM read_parquet(" + targets + ") t "
            "LEFT JOIN read_parquet(" + locators + ") l USING (document_locator_key) "
            "WHERE l.document_locator_key IS NULL",
        )
        orphan_locators = _scalar(
            con,
            "SELECT count(*) FROM read_parquet(" + locators + ") l WHERE NOT EXISTS ("
            "SELECT 1 FROM read_parquet(" + targets + ") t "
            "WHERE t.document_locator_key = l.document_locator_key)",
        )
        disagreements = _scalar(
            con,
            "SELECT count(*) FROM read_parquet(" + targets + ") t "
            "JOIN read_parquet(" + locators + ") l USING (document_locator_key) "
            "WHERE t.document_path <> l.document_path "
            "OR t.document_path_source IS DISTINCT FROM l.document_path_source "
            "OR replace(t.accession, '-', '') <> "
            "replace(l.representative_accession, '-', '') "
            "OR sha256(t.accession || ':' || t.document_path) <> t.document_locator_key "
            "OR sha256(t.source_cik || ':' || t.accession || ':' || t.document_path) "
            "<> t.occurrence_id",
        )
        locator_count = _scalar(
            con,
            "SELECT count(DISTINCT document_locator_key) FROM read_parquet("
            + targets
            + ")",
        )
    if orphan_targets:
        raise CatalogPlanError(
            f"{orphan_targets} target row(s) reference a locator the plan does not hold"
        )
    if orphan_locators:
        raise CatalogPlanError(f"{orphan_locators} locator group(s) hold no target row")
    if disagreements:
        raise CatalogPlanError(
            f"{disagreements} target row(s) disagree with their locator group identity"
        )
    return locator_count


def _scalar(con: Any, query: str) -> int:
    return int(con.execute(query).fetchone()[0])


def _iter_rows(
    target_paths: tuple[Path, ...],
    locator_path: Path,
    batch_rows: int,
) -> Iterator[dict[str, Any]]:
    """Stream target rows joined to their locator group, in stable key order.

    Ordering is DuckDB's, so it spills out-of-core under the connection's memory limit.
    """
    targets = sql_path_list(str(path) for path in target_paths)
    locators = sql_literal(str(locator_path))
    query = (
        "SELECT t.occurrence_id, t.document_locator_key, t.source_cik, t.accession, "
        "t.form, t.filing_date, t.report_date, t.document_path, t.archive_url, "
        "t.document_path_source, l.representative_cik, l.representative_accession "
        f"FROM read_parquet({targets}) t "
        f"JOIN read_parquet({locators}) l USING (document_locator_key) "
        "ORDER BY t.document_locator_key, t.occurrence_id"
    )
    with connect() as con:
        for batch in con.execute(query).to_arrow_reader(batch_rows):
            yield from batch.to_pylist()


def _locator_from_group(row: dict[str, Any], locator_key: str) -> DocumentLocator:
    """Build one locator from the representative identity of its co-filer group."""
    locator = DocumentLocator.from_parts(
        str(row.get("representative_accession") or row.get("accession") or ""),
        str(row.get("document_path") or ""),
        archive_url=row.get("archive_url"),
        form=row.get("form"),
        source_cik=row.get("representative_cik") or row.get("source_cik"),
        document_path_source=row.get("document_path_source"),
    )
    if locator.document_locator_key != locator_key:
        raise CatalogPlanError(
            f"locator {locator_key} does not derive from its published accession "
            "and document path"
        )
    return locator


def _occurrence_from_row(row: dict[str, Any]) -> FilingOccurrence:
    """Map one target row to an occurrence keyed by its locator.

    A catalog plan carries no pre-storage document identity, so ``doc_id`` is the
    locator key: the worker's grouping key and the snapshot's ``blob_hash``.
    """
    report_date = row.get("report_date")
    return FilingOccurrence(
        occurrence_id=str(row["occurrence_id"]),
        source_cik=Cik.from_raw(row["source_cik"]),
        accession=AccessionNumber.from_any(row["accession"]),
        document_path=str(row["document_path"]),
        form=str(row["form"] or ""),
        filing_date=str(row["filing_date"] or ""),
        report_date=None if report_date is None else str(report_date),
        doc_id=str(row["document_locator_key"]),
    )


def _chunk(
    plan_id: str,
    ordinal: int,
    locators: list[DocumentLocator],
    occurrences: list[FilingOccurrence],
) -> ChunkInput:
    """Name a chunk from the plan, the work-order contract, and its ordinal."""
    digest = sha256_text(f"{WORK_ORDER_VERSION}:{plan_id}:{len(locators)}:{ordinal}")[
        :12
    ]
    return ChunkInput(
        chunk_id=f"cat-{ordinal:05d}-{digest}",
        locators=tuple(locators),
        occurrences=tuple(occurrences),
    )


__all__ = [
    "SUPPORTED_PLAN_SCHEMA_VERSIONS",
    "WORK_ORDER_VERSION",
    "CatalogPlan",
    "CatalogPlanError",
    "CatalogPlanMetadata",
]
