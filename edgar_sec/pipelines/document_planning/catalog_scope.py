"""Read and pin the selected occurrence scope of a published catalog plan."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterator

from edgar_sec.domain.filing_catalog.schemas import (
    TARGET_PLAN_SCHEMA_VERSION,
    TARGET_SCHEMA,
)
from edgar_sec.domain.plan.discovery import read_plan_envelope
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.paths import DATA_FILE_NAME, PLAN_FILE_NAME
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.infra.storage.parquet import count_parquet_rows, read_parquet_schema
from .paths import (
    CatalogPaths,
    catalog_form_partition_name,
    resolve_catalog_paths,
    validate_catalog_plan_id,
)

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ACCESSION_RE = re.compile(r"^[0-9]{18}$")
_DEFAULT_BATCH_SIZE = 2_048
_MAX_BATCH_SIZE = 65_536

_FORM_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-/")
_SCOPE_COLUMNS = (
    "occurrence_id",
    "document_locator_key",
    "source_cik",
    "accession",
    "form",
    "filing_date",
    "primary_document",
    "document_path",
    "archive_url",
    "document_path_source",
    "reported_size",
    "is_xbrl",
    "is_inline_xbrl",
    "is_xbrl_numeric",
)


class CatalogScopeError(ValueError):
    """A catalog plan or selected occurrence part violates the scope contract."""


@dataclass(frozen=True, slots=True)
class CatalogSourcePin:
    catalog_plan_id: str
    digest: str


@dataclass(frozen=True, slots=True)
class CatalogPart:
    path: Path
    relative_path: str
    form: str
    rows: int
    sha256: str


@dataclass(frozen=True, slots=True)
class CatalogOccurrence:
    occurrence_id: str
    document_locator_key: str
    source_cik: str
    primary_document: str | None
    document_path: str | None
    archive_url: str | None
    document_path_source: str | None
    reported_size: int | None
    is_xbrl: bool | None
    is_inline_xbrl: bool | None
    is_xbrl_numeric: bool | None


@dataclass(frozen=True, slots=True)
class CatalogScopeAccession:
    accession: str
    form: str
    filing_date: str | None
    occurrences: tuple[CatalogOccurrence, ...]


@dataclass(frozen=True, slots=True)
class CatalogScope:
    """Validated immutable plan metadata and its content-addressed selected parts."""

    pin: CatalogSourcePin
    parts: tuple[CatalogPart, ...]

    def iter_accessions(
        self, batch_size: int = _DEFAULT_BATCH_SIZE
    ) -> Iterator[CatalogScopeAccession]:
        if not 1 <= batch_size <= _MAX_BATCH_SIZE:
            raise ValueError(f"batch_size must be between 1 and {_MAX_BATCH_SIZE}")
        yield from _iter_accessions(self, batch_size)


def _manifest_parts(root: Path, manifest: dict[str, object]) -> tuple[CatalogPart, ...]:
    requested_forms = manifest.get("forms")
    counts_value = manifest.get("counts")
    if not isinstance(requested_forms, list) or not isinstance(counts_value, dict):
        raise CatalogScopeError("catalog plan must declare forms and counts")
    if any(
        not isinstance(form, str)
        or not form
        or form != form.strip()
        or not set(form) <= _FORM_CHARS
        for form in requested_forms
    ):
        raise CatalogScopeError("catalog plan forms contain unsafe values")
    output_forms = list(counts_value)
    if any(
        not isinstance(form, str)
        or not form
        or form != form.strip()
        or not set(form) <= _FORM_CHARS
        for form in output_forms
    ):
        raise CatalogScopeError("catalog plan counts contain unsafe forms")
    partition_names = [catalog_form_partition_name(form) for form in output_forms]
    if len(partition_names) != len(set(partition_names)):
        raise CatalogScopeError("catalog plan forms collide in partition names")
    targets_root = root / "targets"
    if not targets_root.resolve().is_relative_to(root.resolve()):
        raise CatalogScopeError("catalog target parts escape the plan bundle")
    actual_partitions = {
        entry.name
        for entry in targets_root.glob("form=*")
        if entry.is_dir() and (entry / DATA_FILE_NAME).is_file()
    }
    expected_partitions = {f"form={name}" for name in partition_names}
    if expected_partitions - actual_partitions:
        raise CatalogScopeError("catalog target partition is missing")
    if actual_partitions - expected_partitions:
        raise CatalogScopeError("catalog target partitions do not match plan counts")
    counts: dict[str, int] = {}
    for form, count in counts_value.items():
        if (
            not isinstance(form, str)
            or isinstance(count, bool)
            or not isinstance(count, int)
        ):
            raise CatalogScopeError("catalog plan counts must be integer row counts")
        if count < 0:
            raise CatalogScopeError("catalog plan counts cannot be negative")
        counts[form] = count

    listed = manifest.get("target_parts")
    if not isinstance(listed, list):
        raise CatalogScopeError("catalog plan must declare digest-bearing target_parts")
    declared: list[tuple[str, str, int, int, str]] = []
    previous_form = ""
    seen: set[str] = set()
    seen_forms: set[str] = set()
    for record in listed:
        if not isinstance(record, dict):
            raise CatalogScopeError("catalog target part records must be objects")
        relative = record.get("path")
        form = record.get("form")
        rows = record.get("row_count")
        byte_size = record.get("byte_size")
        digest = record.get("sha256")
        if (
            not isinstance(relative, str)
            or not isinstance(form, str)
            or not isinstance(rows, int)
            or isinstance(rows, bool)
            or rows < 0
            or not isinstance(byte_size, int)
            or isinstance(byte_size, bool)
            or byte_size < 0
            or not isinstance(digest, str)
            or not _DIGEST_RE.fullmatch(digest)
        ):
            raise CatalogScopeError(
                "catalog target part has invalid path, form, row_count, byte_size, or sha256"
            )
        part_path = PurePosixPath(relative)
        if (
            part_path.is_absolute()
            or ".." in part_path.parts
            or "\\" in relative
            or not relative.startswith("targets/")
        ):
            raise CatalogScopeError(f"unsafe catalog target part path: {relative!r}")
        expected_path = f"form={catalog_form_partition_name(form)}/data.parquet"
        if form not in counts or relative != f"targets/{expected_path}":
            raise CatalogScopeError(
                f"catalog part does not match declared form: {relative!r}"
            )
        if (
            relative in seen
            or form in seen_forms
            or (previous_form and form < previous_form)
        ):
            raise CatalogScopeError(
                "catalog plan target_parts must be sorted and unique"
            )
        seen.add(relative)
        seen_forms.add(form)
        previous_form = form
        declared.append((relative, form, rows, byte_size, digest))
    if seen_forms != set(counts):
        raise CatalogScopeError(
            "catalog plan target_parts do not list every output form"
        )
    recorded_counts = {form: 0 for form in output_forms}
    for _, form, rows, _, _ in declared:
        recorded_counts[form] += rows
    if recorded_counts != counts:
        raise CatalogScopeError(
            "catalog target part rows do not agree with plan counts"
        )

    parts: list[CatalogPart] = []
    actual_counts = {form: 0 for form in output_forms}
    for relative, form, rows, byte_size, expected_digest in declared:
        candidate = (root / Path(*PurePosixPath(relative).parts)).resolve()
        if not candidate.is_relative_to(root.resolve()):
            raise CatalogScopeError(
                f"catalog target part escapes plan directory: {relative!r}"
            )
        if not candidate.is_file():
            raise CatalogScopeError(f"catalog target part is missing: {relative}")
        actual_digest = file_sha256(candidate)
        if candidate.stat().st_size != byte_size:
            raise CatalogScopeError(
                f"catalog target part byte size mismatch: {relative}"
            )
        if actual_digest != expected_digest:
            raise CatalogScopeError(f"catalog target part digest mismatch: {relative}")
        try:
            schema = read_parquet_schema(candidate)
            actual_rows = count_parquet_rows(candidate)
        except Exception as error:
            raise CatalogScopeError(
                f"catalog target part is corrupt: {relative}"
            ) from error
        if not schema.equals(TARGET_SCHEMA, check_metadata=False):
            raise CatalogScopeError(f"catalog target part schema mismatch: {relative}")
        if actual_rows != rows:
            raise CatalogScopeError(
                f"catalog target part row count mismatch: {relative}"
            )
        actual_counts[form] += actual_rows
        parts.append(CatalogPart(candidate, relative, form, rows, actual_digest))
    if actual_counts != counts:
        raise CatalogScopeError(
            "catalog target part rows do not agree with plan counts"
        )
    if "selected_rows" in manifest and manifest["selected_rows"] != sum(
        counts.values()
    ):
        raise CatalogScopeError("catalog selected_rows does not agree with form counts")
    return tuple(parts)


def resolve_catalog_scope(
    catalog_plan_id: str, paths: CatalogPaths | Path | str | None = None
) -> CatalogScope:
    """Validate a published catalog plan and expose its source pin before reading rows."""
    try:
        validate_catalog_plan_id(catalog_plan_id)
    except (TypeError, ValueError) as error:
        raise CatalogScopeError(
            f"invalid catalog plan id: {catalog_plan_id!r}"
        ) from error
    resolved_paths = resolve_catalog_paths(
        paths if isinstance(paths, Path | str) else None
    )
    if not isinstance(paths, Path | str) and paths is not None:
        resolved_paths = paths
    plans_root = resolved_paths.plans_root.resolve()
    root = resolved_paths.plan_dir(catalog_plan_id).resolve()
    if not root.is_relative_to(plans_root):
        raise CatalogScopeError("catalog plan escapes its published plans root")
    manifest_path = root / PLAN_FILE_NAME
    digest_before = file_sha256(manifest_path)
    envelope = read_plan_envelope(root)
    if envelope is None or envelope.plan_id != catalog_plan_id:
        raise CatalogScopeError(
            f"catalog plan envelope is missing or invalid: {catalog_plan_id}"
        )
    manifest = envelope.raw
    if manifest.get("plan_id") != catalog_plan_id:
        raise CatalogScopeError(
            "catalog plan id does not match its published directory"
        )
    if not str(manifest.get("catalog_id") or "").strip():
        raise CatalogScopeError("catalog plan is missing catalog_id")
    if not str(manifest.get("plan_fingerprint") or "").strip():
        raise CatalogScopeError("catalog plan is missing plan_fingerprint")
    if manifest.get("scope") not in {"deterministic", "policy"}:
        raise CatalogScopeError("catalog plan has an unsupported scope")
    if manifest.get("plan_schema_version") != TARGET_PLAN_SCHEMA_VERSION:
        raise CatalogScopeError("catalog plan schema version is unsupported")
    if not envelope.manifest_path.resolve().is_relative_to(root):
        raise CatalogScopeError("catalog plan manifest escapes its bundle")
    manifest_digest = file_sha256(envelope.manifest_path)
    if digest_before != manifest_digest:
        raise CatalogScopeError("catalog plan manifest changed during validation")
    parts = _manifest_parts(root, manifest)
    digest = canonical_hash(
        {
            "manifest_sha256": manifest_digest,
            "parts": [
                {
                    "path": part.relative_path,
                    "form": part.form,
                    "rows": part.rows,
                    "sha256": part.sha256,
                }
                for part in parts
            ],
        }
    )
    return CatalogScope(CatalogSourcePin(catalog_plan_id, digest), parts)


def _occurrence(row: dict[str, object]) -> CatalogOccurrence:
    occurrence_id = row["occurrence_id"]
    locator_key = row["document_locator_key"]
    source_cik = row["source_cik"]
    if not all(
        isinstance(value, str) and value
        for value in (occurrence_id, locator_key, source_cik)
    ):
        raise CatalogScopeError("catalog occurrence is missing identity metadata")
    return CatalogOccurrence(
        occurrence_id,
        locator_key,
        source_cik,
        row["primary_document"],
        row["document_path"],
        row["archive_url"],
        row["document_path_source"],
        row["reported_size"],
        row["is_xbrl"],
        row["is_inline_xbrl"],
        row["is_xbrl_numeric"],
    )


def _iter_accessions(
    scope: CatalogScope, batch_size: int
) -> Iterator[CatalogScopeAccession]:
    for part in scope.parts:
        if not part.path.is_file() or file_sha256(part.path) != part.sha256:
            raise CatalogScopeError(
                f"catalog target part changed after pinning: {part.relative_path}"
            )
    if not scope.parts:
        return
    columns = ", ".join(f'"{column}"' for column in _SCOPE_COLUMNS)
    query = (
        f"SELECT filename, {columns} FROM read_parquet(?, filename = true, "
        "hive_partitioning = false) "
        "ORDER BY replace(accession, '-', ''), occurrence_id"
    )
    part_forms = {str(part.path): part.form for part in scope.parts}
    counts: dict[str, int] = {}
    current_accession: str | None = None
    current_form: str | None = None
    current_date: str | None = None
    occurrences: dict[str, CatalogOccurrence] = {}
    try:
        with connect() as con:
            reader = con.execute(
                query, [[str(part.path) for part in scope.parts]]
            ).to_arrow_reader(batch_size)
            for batch in reader:
                for row in batch.select(("filename", *_SCOPE_COLUMNS)).to_pylist():
                    if part_forms.get(row.get("filename")) != row.get("form"):
                        raise CatalogScopeError(
                            "catalog row form does not match its target part"
                        )
                    raw_accession = row.get("accession")
                    accession = str(raw_accession or "").replace("-", "").strip()
                    if not _ACCESSION_RE.fullmatch(accession):
                        raise CatalogScopeError(
                            f"invalid catalog accession: {raw_accession!r}"
                        )
                    form = str(row.get("form") or "").strip()
                    if not form:
                        raise CatalogScopeError(
                            f"catalog accession has no form: {accession}"
                        )
                    filing_date = str(row.get("filing_date") or "").strip() or None
                    counts[form] = counts.get(form, 0) + 1
                    if current_accession != accession:
                        if current_accession is not None:
                            yield CatalogScopeAccession(
                                current_accession,
                                current_form or "",
                                current_date,
                                tuple(occurrences[key] for key in sorted(occurrences)),
                            )
                        current_accession = accession
                        current_form = form
                        current_date = filing_date
                        occurrences = {}
                    elif current_form != form:
                        raise CatalogScopeError(
                            f"conflicting catalog forms for accession {accession}"
                        )
                    elif current_date and filing_date and current_date != filing_date:
                        raise CatalogScopeError(
                            f"conflicting catalog filing dates for accession {accession}"
                        )
                    elif current_date is None:
                        current_date = filing_date
                    occurrence = _occurrence(row)
                    previous = occurrences.get(occurrence.occurrence_id)
                    if previous is not None and previous != occurrence:
                        raise CatalogScopeError(
                            f"conflicting locator metadata for occurrence {occurrence.occurrence_id}"
                        )
                    occurrences[occurrence.occurrence_id] = occurrence
    except CatalogScopeError:
        raise
    except Exception as error:
        raise CatalogScopeError(
            f"unable to stream catalog target parts: {error}"
        ) from error
    if current_accession is not None:
        yield CatalogScopeAccession(
            current_accession,
            current_form or "",
            current_date,
            tuple(occurrences[key] for key in sorted(occurrences)),
        )
    expected_counts = {part.form: 0 for part in scope.parts}
    for form, count in counts.items():
        expected_counts[form] = expected_counts.get(form, 0) + count
    declared_counts: dict[str, int] = {}
    for part in scope.parts:
        declared_counts[part.form] = declared_counts.get(part.form, 0) + part.rows
    if expected_counts != declared_counts:
        raise CatalogScopeError(
            "streamed catalog rows do not agree with pinned part counts"
        )


def iter_catalog_scope(
    catalog_plan_id: str, paths: CatalogPaths | Path | str | None = None
) -> Iterator[CatalogScopeAccession]:
    """Yield sorted, unique accession facts from the validated catalog plan."""
    yield from resolve_catalog_scope(catalog_plan_id, paths).iter_accessions()


__all__ = [
    "CatalogOccurrence",
    "CatalogPart",
    "CatalogScope",
    "CatalogScopeAccession",
    "CatalogScopeError",
    "CatalogSourcePin",
    "iter_catalog_scope",
    "resolve_catalog_scope",
]
