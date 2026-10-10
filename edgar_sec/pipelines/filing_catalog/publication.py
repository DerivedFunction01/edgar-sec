"""Immutable publication contract for target-plan bundles.
Each bundle is staged as a *sibling* of its destination, so the final
``os.replace`` stays on one filesystem and is atomic. An exact rerun reuses the
bundle; an incomplete or diverging directory is a conflict, not a rewrite.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from edgar_sec.domain.filing_catalog.schemas import SCOPE_POLICY
from edgar_sec.domain.filing_catalog.schemas import (
    READABLE_TARGET_PLAN_SCHEMA_VERSIONS,
    TARGET_PLAN_SCHEMA_VERSION,
)
from edgar_sec.foundation.hashing import file_sha256, is_sha256_hex_digest
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.foundation.runtime.paths import DATA_FILE_NAME, PLAN_FILE_NAME
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.duckdb import connect, sql_literal
from edgar_sec.pipelines.filing_catalog.paths import (
    FORM_PARTITION_GLOB,
    LOCATOR_GROUPS_FILE,
    PLAN_TARGETS_DIR,
    REQUIRED_PLAN_FILES,
    SEED_FILERS_FILE,
    SELECTION_REPORT_FILE,
    form_partition_directory,
    form_partition_name,
    plan_target_file_path,
)


class PlanConflictError(RuntimeError):
    """A published plan directory exists but does not match the request."""


def plan_identity(payload: dict[str, Any]) -> str:
    """Derive a content-addressed plan id from the request defining it.

    The same catalog and filters always yield the same id.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def plan_locator_keys(plan_dir: str | Path) -> list[str]:
    """Read a published plan's selected locator keys, in file order.
    An in-memory connection writing nothing beside the plan, so an interrupted read
    leaves no stray state in an immutable bundle.
    """
    root = Path(plan_dir).resolve()
    locator_path = root / LOCATOR_GROUPS_FILE
    if not locator_path.is_file():
        raise FileNotFoundError(f"plan locator groups not found: {locator_path}")
    with connect() as con:
        rows = con.execute(
            f"SELECT document_locator_key FROM read_parquet("
            f"{sql_literal(str(locator_path))}) ORDER BY document_locator_key"
        ).fetchall()
    return [str(row[0]) for row in rows]


def plan_fingerprint(plan_meta: dict[str, Any], locator_keys: list[str]) -> str:
    """Content digest of a plan's identity and its selected locators.

    Narrow on purpose: the work order, not every Parquet in the bundle.
    """
    return canonical_hash(
        {
            "plan_id": plan_meta.get("plan_id"),
            "catalog_id": plan_meta.get("catalog_id"),
            "scope": plan_meta.get("scope"),
            "locator_keys": sorted(locator_keys),
        }
    )[:32]


def plan_fingerprint_from_sorted_keys(
    plan_meta: dict[str, Any], locator_keys: Iterable[str]
) -> str:
    """Hash an ordered locator stream with the same contract as plan_fingerprint."""
    digest = hashlib.sha256()
    digest.update(
        (
            b'{"catalog_id":'
            + json.dumps(plan_meta.get("catalog_id"), separators=(",", ":")).encode()
            + b',"locator_keys":['
        )
    )
    first = True
    for key in locator_keys:
        if not first:
            digest.update(b",")
        digest.update(json.dumps(key, separators=(",", ":")).encode())
        first = False
    digest.update(
        b'],"plan_id":'
        + json.dumps(plan_meta.get("plan_id"), separators=(",", ":")).encode()
        + b',"scope":'
        + json.dumps(plan_meta.get("scope"), separators=(",", ":")).encode()
        + b"}"
    )
    return digest.hexdigest()[:32]


def plan_fingerprint_from_plan(plan_dir: str | Path, plan_meta: dict[str, Any]) -> str:
    """Verify selection identity without materializing all locator keys."""
    locator_path = Path(plan_dir).resolve() / LOCATOR_GROUPS_FILE
    if not locator_path.is_file():
        raise FileNotFoundError(f"plan locator groups not found: {locator_path}")
    with connect() as con:
        reader = con.execute(
            "SELECT document_locator_key FROM read_parquet("
            + sql_literal(str(locator_path))
            + ") ORDER BY document_locator_key"
        ).to_arrow_reader(2048)
        return plan_fingerprint_from_sorted_keys(
            plan_meta,
            (str(key) for batch in reader for key in batch.column(0).to_pylist()),
        )


def plan_bundle_complete(plan_dir: Path, scope: str = "") -> bool:
    """Report whether a plan bundle holds every required artifact.
    The partition set is matched against the plan's recorded ``counts``, so an empty
    plan is still reusable while a lost shard is caught.
    """
    if not all((plan_dir / name).is_file() for name in REQUIRED_PLAN_FILES):
        return False
    if scope == SCOPE_POLICY and not (plan_dir / SEED_FILERS_FILE).is_file():
        return False
    targets_dir = plan_dir / PLAN_TARGETS_DIR
    if not targets_dir.is_dir():
        return False
    published = _load_plan_json(plan_dir)
    if published is None:
        return False
    counts = published.get("counts")
    if not isinstance(counts, dict):
        return False
    expected = {form_partition_directory(form) for form in counts}
    present = {
        entry.name
        for entry in targets_dir.glob(FORM_PARTITION_GLOB)
        if entry.is_dir() and (entry / DATA_FILE_NAME).is_file()
    }
    if present != expected:
        return False
    if "target_parts" in published:
        return _target_parts_complete(plan_dir, published, counts)
    return published.get("plan_schema_version") != TARGET_PLAN_SCHEMA_VERSION


def _target_parts_complete(
    plan_dir: Path, published: dict[str, Any], counts: dict[str, Any]
) -> bool:
    parts = published.get("target_parts")
    if not isinstance(parts, list):
        return False
    expected = {
        (form, plan_target_file_path(form, DATA_FILE_NAME)): row_count
        for form, row_count in counts.items()
    }
    if len(parts) != len(expected):
        return False
    observed: set[tuple[str, str]] = set()
    for part in parts:
        if not isinstance(part, dict):
            return False
        form, relative, rows, digest = (
            part.get("form"),
            part.get("path"),
            part.get("row_count"),
            part.get("sha256"),
        )
        key = (form, relative)
        if not isinstance(form, str) or not isinstance(relative, str):
            return False
        if (
            key not in expected
            or key in observed
            or not isinstance(rows, int)
            or isinstance(rows, bool)
            or rows != expected[key]
        ):
            return False
        if not isinstance(digest, str) or not is_sha256_hex_digest(digest):
            return False
        path = plan_dir / relative
        if not path.is_file():
            return False
        if part.get("byte_size") != path.stat().st_size:
            return False
        if file_sha256(path) != digest:
            return False
        observed.add(key)
    return observed == set(expected)


def _load_plan_json(plan_dir: Path) -> dict[str, Any] | None:
    path = plan_dir / PLAN_FILE_NAME
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _verify_selection_fingerprint(plan_dir: Path, published: dict[str, Any]) -> None:
    """Refuse a bundle whose work order no longer matches its selection.
    A bundle recording no fingerprint predates the contract carrying one and is
    refused rather than silently recomputed.
    """
    recorded = str(published.get("plan_fingerprint") or "")
    if not recorded:
        raise PlanConflictError(
            f"plan bundle at {plan_dir} records no selection fingerprint; "
            "remove it and rerun to republish under the current plan contract"
        )
    actual = plan_fingerprint(published, plan_locator_keys(plan_dir))
    if actual != recorded:
        raise PlanConflictError(
            f"plan bundle at {plan_dir} no longer matches its selection fingerprint "
            f"(recorded {recorded}, found {actual}); remove it and republish"
        )


def reuse_existing_plan(
    final_dir: Path,
    plan_id: str,
    scope: str,
    *,
    expected_meta: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return a published bundle when it already satisfies the request.
    ``None`` when nothing is published; a conflict rather than a rewrite when a directory
    exists but is incomplete or describes a different request.
    """
    if not final_dir.exists():
        return None

    published = _load_plan_json(final_dir)
    if published is None:
        raise PlanConflictError(f"plan bundle at {final_dir} has no readable plan.json")

    # Identity before completeness: a directory holding a different request is a
    # conflict whether or not it is also incomplete, and reporting it as merely
    # incomplete would send an operator to rebuild a bundle that can never
    # satisfy this request.
    if published.get("plan_id") != plan_id or published.get("scope") != scope:
        raise PlanConflictError(
            f"plan bundle at {final_dir} describes a different request; remove "
            "it or publish under a different plan id"
        )

    if not plan_bundle_complete(final_dir, scope):
        raise PlanConflictError(
            f"incomplete plan bundle at {final_dir}; remove it and rerun to republish"
        )

    _verify_selection_fingerprint(final_dir, published)

    if expected_meta:
        mismatched = {
            key: (expected_meta[key], published.get(key))
            for key in expected_meta
            if published.get(key) != expected_meta[key]
        }
        if mismatched:
            raise PlanConflictError(
                f"plan bundle at {final_dir} diverges from the current request: "
                f"{sorted(mismatched)}"
            )

    return published


def publish_plan_bundle(staging_dir: Path, final_dir: Path) -> None:
    """Move a fully built staging bundle into its published location.
    ``os.replace`` is atomic only within a filesystem, hence the sibling staging dir.
    """
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging_dir, final_dir)


@contextmanager
def staged_plan_bundle(final_dir: Path, plan_id: str) -> Iterator[Path]:
    """Yield a sibling staging directory, publishing it atomically.
    Any failure removes it, so a partial bundle is never left where a later run could
    mistake it for published state.
    """
    staging_dir = final_dir.parent / f".{final_dir.name}.staging.{plan_id}"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield staging_dir
    except BaseException:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    else:
        if final_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise PlanConflictError(
                f"plan bundle appeared at {final_dir} during publication"
            )
        publish_plan_bundle(staging_dir, final_dir)


def write_plan_documents(
    staging_dir: Path,
    plan_meta: dict[str, Any],
    selection_report: dict[str, Any],
) -> dict[str, Any]:
    """Write the two required JSON documents of a plan bundle.
    The fingerprint is stamped from the locator groups the bundle already holds, and
    returned so a caller rewriting ``plan.json`` carries the stamp with it.
    """
    stamped = dict(plan_meta)
    stamped["target_parts"] = _describe_target_parts(staging_dir, stamped.get("counts"))
    stamped["plan_fingerprint"] = plan_fingerprint(
        stamped, plan_locator_keys(staging_dir)
    )
    atomic_write_json(staging_dir / PLAN_FILE_NAME, stamped, indent=2)
    atomic_write_json(staging_dir / SELECTION_REPORT_FILE, selection_report, indent=2)
    return stamped


def _describe_target_parts(staging_dir: Path, counts: Any) -> list[dict[str, Any]]:
    if not isinstance(counts, dict):
        raise PlanConflictError("plan counts must be an object before publication")
    parts: list[dict[str, Any]] = []
    partitions: set[str] = set()
    for form in sorted(counts):
        row_count = counts[form]
        if (
            not isinstance(form, str)
            or not isinstance(row_count, int)
            or isinstance(row_count, bool)
            or row_count < 0
        ):
            raise PlanConflictError("plan counts contain an invalid form or row count")
        partition = form_partition_name(form)
        if partition in partitions:
            raise PlanConflictError("plan forms collide in target partition names")
        partitions.add(partition)
        relative = plan_target_file_path(form, DATA_FILE_NAME)
        path = staging_dir / relative
        if not path.is_file():
            raise PlanConflictError(
                f"target part is missing before publication: {relative}"
            )
        parts.append(
            {
                "form": form,
                "path": relative,
                "row_count": row_count,
                "byte_size": path.stat().st_size,
                "sha256": file_sha256(path),
            }
        )
    return parts


__all__ = [
    "PlanConflictError",
    "plan_bundle_complete",
    "plan_fingerprint",
    "plan_fingerprint_from_plan",
    "plan_fingerprint_from_sorted_keys",
    "plan_identity",
    "plan_locator_keys",
    "publish_plan_bundle",
    "reuse_existing_plan",
    "staged_plan_bundle",
    "write_plan_documents",
]
