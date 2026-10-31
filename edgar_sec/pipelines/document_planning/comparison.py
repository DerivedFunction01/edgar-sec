"""Compare immutable document plans and normalized target profiles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa

from edgar_sec.infra.storage.duckdb import connect, sql_identifier, sql_path_list
from edgar_sec.pipelines.document_planning.discovery import (
    PublishedDocumentPlan,
    read_published_plan,
)
from edgar_sec.pipelines.document_planning.paths import DocumentPlanningPaths
from edgar_sec.pipelines.document_planning.profiles import (
    ResolvedProfile,
    load_profile,
)
from edgar_sec.pipelines.document_planning.schemas import TARGET_SCHEMA


def _profile_rules(profile: ResolvedProfile) -> dict[tuple[str, str, str, bool], dict]:
    rules = {}
    for rule in profile.rules:
        for target in rule.targets:
            key = (rule.form_selector, target.role, target.type, target.optional)
            policy = (
                list(
                    operation.value
                    for operation in target.acquisition_policy.operations
                )
                if target.acquisition_policy is not None
                else None
            )
            rules[key] = {
                "form_selector": key[0],
                "role": key[1],
                "type": key[2],
                "optional": key[3],
                "catalog_direct_selection": target.catalog_direct_selection,
                "acquisition_operations": policy,
            }
    return rules


def compare_profiles(
    base_profile_id: str,
    new_profile_id: str,
    paths: DocumentPlanningPaths,
) -> dict[str, Any]:
    base = load_profile(base_profile_id, paths.profiles_root)
    new = load_profile(new_profile_id, paths.profiles_root)
    base_rules = _profile_rules(base)
    new_rules = _profile_rules(new)
    added = [new_rules[key] for key in sorted(new_rules.keys() - base_rules.keys())]
    removed = [base_rules[key] for key in sorted(base_rules.keys() - new_rules.keys())]
    changed = [
        {"base": base_rules[key], "new": new_rules[key]}
        for key in sorted(base_rules.keys() & new_rules.keys())
        if base_rules[key] != new_rules[key]
    ]
    return {
        "status": "compared",
        "base": _profile_pin(base),
        "new": _profile_pin(new),
        "added": added,
        "removed": removed,
        "changed": changed,
    }


def _profile_pin(profile: ResolvedProfile) -> dict[str, str]:
    return {
        "profile_id": profile.profile_id,
        "version": profile.version,
        "digest": profile.digest,
    }


def _pinned_profile_diff(
    base: PublishedDocumentPlan,
    new: PublishedDocumentPlan,
    paths: DocumentPlanningPaths,
) -> dict[str, Any]:
    pins = []
    for plan in (base, new):
        manifest = plan.manifest
        try:
            profile = load_profile(str(manifest["profile_id"]), paths.profiles_root)
        except (KeyError, OSError, ValueError):
            return {"status": "unavailable", "reason": "pinned profile is not present"}
        if profile.digest != manifest.get("profile_digest"):
            return {
                "status": "unavailable",
                "reason": "current profile does not match the plan's pinned digest",
                "plan_id": plan.plan_id,
                "profile_id": profile.profile_id,
                "pinned_digest": manifest.get("profile_digest"),
                "current_digest": profile.digest,
            }
        pins.append(profile)
    base_rules = _profile_rules(pins[0])
    new_rules = _profile_rules(pins[1])
    return {
        "status": "compared",
        "base": _profile_pin(pins[0]),
        "new": _profile_pin(pins[1]),
        "added": [
            new_rules[key] for key in sorted(new_rules.keys() - base_rules.keys())
        ],
        "removed": [
            base_rules[key] for key in sorted(base_rules.keys() - new_rules.keys())
        ],
        "changed": [
            {"base": base_rules[key], "new": new_rules[key]}
            for key in sorted(base_rules.keys() & new_rules.keys())
            if base_rules[key] != new_rules[key]
        ],
    }


def _target_parts(plan: PublishedDocumentPlan) -> list[Path]:
    result = []
    for part in plan.manifest["parts"]:
        if part["relation"] != "targets":
            continue
        path = (plan.root / part["path"]).resolve()
        if not path.is_relative_to(plan.root.resolve()):
            raise ValueError("target part escapes its plan bundle")
        result.append(path)
    return result


def _register_targets(con, name: str, parts: list[Path]) -> None:
    view_name = sql_identifier(name)
    if parts:
        paths_sql = sql_path_list([str(path) for path in parts])
        con.execute(
            f"CREATE TEMP VIEW {view_name} AS SELECT * FROM read_parquet({paths_sql})"
        )
    else:
        empty_name = f"{name}_empty"
        con.register(empty_name, pa.Table.from_batches([], schema=TARGET_SCHEMA))
        empty_identifier = sql_identifier(empty_name)
        con.execute(f"CREATE TEMP VIEW {view_name} AS SELECT * FROM {empty_identifier}")


def _source_pins(plan: PublishedDocumentPlan) -> dict[str, dict[str, Any]]:
    manifest = plan.manifest
    return {
        "catalog_plan": {
            "id": manifest["catalog_plan_id"],
            "digest": manifest["catalog_plan_digest"],
        },
        "inventory_snapshot": {
            "id": manifest["inventory_snapshot_id"],
            "digest": manifest["inventory_snapshot_digest"],
        },
    }


def _target_differences(base: PublishedDocumentPlan, new: PublishedDocumentPlan):
    base_pins = _source_pins(base)
    new_pins = _source_pins(new)
    same_sources = base_pins == new_pins
    con = connect()
    try:
        _register_targets(con, "base_targets", _target_parts(base))
        _register_targets(con, "new_targets", _target_parts(new))
        cursor = con.execute(
            "SELECT coalesce(b.accession, n.accession), "
            "coalesce(b.request_id, n.request_id), "
            "coalesce(b.source_origin, n.source_origin), "
            "coalesce(b.inventory_entry_id, n.inventory_entry_id), "
            "b.target_id, n.target_id, b.status, n.status, "
            "b.status_reason, n.status_reason "
            "FROM base_targets b FULL OUTER JOIN new_targets n "
            "ON b.accession = n.accession AND b.request_id = n.request_id "
            "AND b.source_origin = n.source_origin "
            "AND b.inventory_entry_id IS NOT DISTINCT FROM n.inventory_entry_id "
            "WHERE b.target_id IS NULL OR n.target_id IS NULL "
            "OR b.status IS DISTINCT FROM n.status "
            "OR b.status_reason IS DISTINCT FROM n.status_reason "
            "ORDER BY 1, 2, 3, 4"
        )
        counts = {
            "added": 0,
            "removed": 0,
            "status_transition": 0,
            "status_reason_change": 0,
        }
        changes = []
        for row in iter(cursor.fetchone, None):
            (
                accession,
                request_id,
                source_origin,
                inventory_entry_id,
                base_target_id,
                new_target_id,
                base_status,
                new_status,
                base_reason,
                new_reason,
            ) = row
            identity = {
                "accession": accession,
                "request_id": request_id,
                "source_origin": source_origin,
                "inventory_entry_id": inventory_entry_id,
            }
            if base_target_id is None:
                counts["added"] += 1
                changes.append(
                    {
                        "kind": "added",
                        **identity,
                        "new_status": new_status,
                        "new_status_reason": new_reason,
                    }
                )
            elif new_target_id is None:
                counts["removed"] += 1
                changes.append(
                    {
                        "kind": "removed",
                        **identity,
                        "base_status": base_status,
                        "base_status_reason": base_reason,
                    }
                )
            else:
                status_changed = base_status != new_status
                reason_changed = base_reason != new_reason
                if status_changed and same_sources:
                    counts["status_transition"] += 1
                    changes.append(
                        {
                            "kind": "status_transition",
                            **identity,
                            "base_status": base_status,
                            "new_status": new_status,
                            "base_status_reason": base_reason,
                            "new_status_reason": new_reason,
                        }
                    )
                elif reason_changed:
                    counts["status_reason_change"] += 1
                    changes.append(
                        {
                            "kind": "status_reason_change",
                            **identity,
                            "status": base_status
                            if base_status == new_status
                            else None,
                            "base_status_reason": base_reason,
                            "new_status_reason": new_reason,
                        }
                    )
        return counts, changes
    finally:
        con.close()


def compare_target_plans(
    base_plan_id: str,
    new_plan_id: str,
    paths: DocumentPlanningPaths,
) -> dict[str, Any]:
    base = read_published_plan(base_plan_id, paths)
    new = read_published_plan(new_plan_id, paths)
    counts, changes = _target_differences(base, new)
    base_sources = _source_pins(base)
    new_sources = _source_pins(new)
    source_changes = [
        {
            "source": source,
            "base": base_sources[source],
            "new": new_sources[source],
        }
        for source in base_sources
        if base_sources[source] != new_sources[source]
    ]
    return {
        "schema_version": 1,
        "base_plan_id": base.plan_id,
        "new_plan_id": new.plan_id,
        "provenance": {
            "base": base_sources,
            "new": new_sources,
            "changes": source_changes,
            "outcome_transitions_comparable": not source_changes,
        },
        "target_diff_counts": counts,
        "target_differences": changes,
        "profile_rule_diff": _pinned_profile_diff(base, new, paths),
    }


__all__ = ["compare_profiles", "compare_target_plans"]
