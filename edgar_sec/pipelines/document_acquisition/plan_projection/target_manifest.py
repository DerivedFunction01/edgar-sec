"""Validate a target bundle's manifest against its canonical identity."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from edgar_sec.foundation.hashing import is_sha256_hex_digest
from edgar_sec.foundation.runtime.paths import PLAN_FILE_NAME
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.pipelines.document_acquisition.plan_projection.target_contract import (
    _PLAN_BUNDLE_SCHEMA_VERSION,
    _TARGET_MATCHER_VERSION,
    _TARGET_SCHEMA_VERSION,
    TargetPlanError,
)
from edgar_sec.pipelines.document_acquisition.schemas import (
    OPERATION_INPUT_SCHEMA_VERSION,
    SOURCE_REQUEST_SCHEMA_VERSION,
    TARGET_OPERATION_SCHEMA_VERSION,
)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TargetPlanError(f"duplicate manifest field: {key}")
        result[key] = value
    return result


def _read_manifest(root: Path) -> dict[str, Any]:
    path = root / PLAN_FILE_NAME
    if (
        path.is_symlink()
        or not path.is_file()
        or not path.resolve().is_relative_to(root)
    ):
        raise TargetPlanError("target-plan manifest is missing or unsafe")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TargetPlanError) as error:
        raise TargetPlanError("target-plan manifest is unreadable") from error
    if not isinstance(value, dict):
        raise TargetPlanError("target-plan manifest must be an object")
    return value


def _validate_manifest(plan_dir: Path) -> tuple[Path, dict[str, Any]]:
    if plan_dir.is_symlink() or not plan_dir.is_dir():
        raise TargetPlanError("target-plan directory is missing or unsafe")
    root = plan_dir.resolve()
    manifest = _read_manifest(root)
    plan_id = manifest.get("plan_id")
    if not isinstance(plan_id, str) or not plan_id or root.name != plan_id:
        raise TargetPlanError("plan ID does not match its bundle directory")
    bundle_schema_version = manifest.get("bundle_schema_version")
    if (
        type(bundle_schema_version) is not int
        or bundle_schema_version != _PLAN_BUNDLE_SCHEMA_VERSION
    ):
        raise TargetPlanError(
            "missing or unsupported target-plan bundle schema version; "
            f"requires bundle version {_PLAN_BUNDLE_SCHEMA_VERSION}"
        )
    if manifest.get("matcher_version") != _TARGET_MATCHER_VERSION:
        raise TargetPlanError(
            f"unsupported target matcher version; requires {_TARGET_MATCHER_VERSION}"
        )
    target_schema_version = manifest.get("target_schema_version")
    if (
        type(target_schema_version) is not int
        or target_schema_version != _TARGET_SCHEMA_VERSION
    ):
        raise TargetPlanError("unsupported target schema version")
    schema_versions = {
        "target_operation_schema_version": TARGET_OPERATION_SCHEMA_VERSION,
        "source_request_schema_version": SOURCE_REQUEST_SCHEMA_VERSION,
        "operation_input_schema_version": OPERATION_INPUT_SCHEMA_VERSION,
    }
    for name, expected in schema_versions.items():
        value = manifest.get(name)
        if type(value) is not int or value != expected:
            raise TargetPlanError(f"unsupported or mismatched {name}")
    plan_digest = manifest.get("plan_digest")
    unsigned = dict(manifest)
    unsigned.pop("plan_digest", None)
    if not is_sha256_hex_digest(plan_digest) or canonical_hash(unsigned) != plan_digest:
        raise TargetPlanError("target-plan manifest digest mismatch")
    identity = manifest.get("plan_identity")
    if not isinstance(identity, dict):
        raise TargetPlanError("target-plan identity is missing")
    if any(
        type(identity.get(name)) is not int or identity.get(name) != expected
        for name, expected in schema_versions.items()
    ):
        raise TargetPlanError("plan relation schema versions do not match identity")
    identity_bundle_schema_version = identity.get("bundle_schema_version")
    if (
        type(identity_bundle_schema_version) is not int
        or identity_bundle_schema_version != _PLAN_BUNDLE_SCHEMA_VERSION
    ):
        raise TargetPlanError(
            "missing or unsupported bundle schema version in target-plan identity"
        )
    if identity.get("matcher_version") != _TARGET_MATCHER_VERSION:
        raise TargetPlanError(
            "unsupported target matcher version in target-plan identity"
        )
    identity_target_schema_version = identity.get("target_schema_version")
    if (
        type(identity_target_schema_version) is not int
        or identity_target_schema_version != _TARGET_SCHEMA_VERSION
        or manifest.get("target_schema_version") != identity_target_schema_version
        or manifest.get("matcher_version") != identity.get("matcher_version")
        or manifest.get("profile_digest") != identity.get("profile_digest")
        or manifest.get("catalog_plan_id") != identity.get("catalog_plan_id")
        or manifest.get("catalog_plan_digest") != identity.get("catalog_plan_digest")
        or manifest.get("inventory_snapshot_id")
        != identity.get("inventory_snapshot_id")
        or manifest.get("inventory_snapshot_digest")
        != identity.get("inventory_snapshot_digest")
    ):
        raise TargetPlanError("target-plan metadata does not match its identity")
    if f"dplan_{canonical_hash(identity)[:32]}" != plan_id:
        raise TargetPlanError("plan ID does not match its canonical identity")
    if not is_sha256_hex_digest(manifest.get("profile_digest")):
        raise TargetPlanError("profile digest is invalid")
    if not isinstance(manifest.get("profile_id"), str) or not manifest["profile_id"]:
        raise TargetPlanError("target plan is missing its profile ID")
    for name in ("profile_schema_version", "profile_version"):
        if not isinstance(manifest.get(name), str) or not manifest[name]:
            raise TargetPlanError(f"target plan is missing {name}")
    catalog_id = manifest.get("catalog_plan_id")
    catalog_digest = manifest.get("catalog_plan_digest")
    if not isinstance(catalog_id, str) or not catalog_id:
        raise TargetPlanError("catalog plan ID is required")
    if not is_sha256_hex_digest(catalog_digest):
        raise TargetPlanError("catalog plan digest is required and must be SHA-256")
    inventory_id = manifest.get("inventory_snapshot_id")
    inventory_digest = manifest.get("inventory_snapshot_digest")
    if (inventory_id is None) != (inventory_digest is None):
        raise TargetPlanError(
            "inventory snapshot ID and digest must be pinned together"
        )
    if inventory_id is not None and (
        not isinstance(inventory_id, str)
        or not inventory_id
        or not is_sha256_hex_digest(inventory_digest)
    ):
        raise TargetPlanError("inventory snapshot pin is invalid")
    count = manifest.get("target_row_count")
    statuses = manifest.get("status_counts")
    if (
        not isinstance(count, int)
        or isinstance(count, bool)
        or count < 0
        or not isinstance(statuses, dict)
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in statuses.values()
        )
        or sum(statuses.values()) != count
    ):
        raise TargetPlanError("target-plan row counts are invalid")
    return root, manifest
