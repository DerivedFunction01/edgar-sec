"""Manifest-only discovery for inventory fixtures and catalog plans."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from edgar_sec.foundation.runtime.paths import resolve_paths
from edgar_sec.pipelines.document_inventory.fixture_store.discovery import (
    discover_index_fixtures,
)
from edgar_sec.pipelines.document_inventory.paths import (
    inventory_paths,
    resolve_filing_catalog_paths,
)
from edgar_sec.pipelines.filing_catalog.discovery import (
    discover_plans as _discover_plans,
)


def discover_plans(artifacts_root: str | Path | None = None) -> list[dict[str, Any]]:
    paths = resolve_filing_catalog_paths(artifacts_root)
    return _discover_plans(paths)


def discover_fixtures(artifacts_root: str | Path | None = None) -> list[dict[str, Any]]:
    root = (
        Path(artifacts_root)
        if artifacts_root is not None
        else resolve_paths().artifacts_root
    )
    return discover_index_fixtures(inventory_paths(root).fixtures_root)


def plan_summary(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "plan_id": plan.get("plan_id"),
        "catalog_id": plan.get("catalog_id"),
        "scope": plan.get("scope"),
        "forms": plan.get("forms") or [],
        "unique_locators_count": int(plan.get("unique_locators_count") or 0),
        "selected_rows": plan.get("selected_rows"),
    }


def fixture_summary(fixture: dict[str, Any]) -> dict[str, Any]:
    return {
        "fixture_id": fixture.get("fixture_id"),
        "schema_version": fixture.get("schema_version"),
        "capture_state": fixture.get("capture_state", "unknown"),
        "page_count": int(fixture.get("page_count") or 0),
        "accession_count": int(fixture.get("accession_count") or 0),
        "membership_count": int(fixture.get("membership_count") or 0),
        "contributions": fixture.get("contributions") or [],
    }


def _resolve_choice(
    choices: list[dict[str, Any]],
    describe: Callable[[dict[str, Any]], str],
    select: Callable[[list[str]], str],
) -> dict[str, Any] | None:
    if not choices:
        return None
    if len(choices) == 1:
        return choices[0]
    lines = [f"  {i}. {describe(choice)}" for i, choice in enumerate(choices, 1)]
    try:
        index = int(select(lines))
    except (TypeError, ValueError):
        return None
    return choices[index - 1] if 1 <= index <= len(choices) else None


def resolve_plan_choice(
    plans: list[dict[str, Any]], *, select: Callable[[list[str]], str]
) -> dict[str, Any] | None:
    return _resolve_choice(
        plans,
        lambda plan: (
            f"{plan.get('plan_id', '?')}  catalog {plan.get('catalog_id', '?')}  "
            f"{plan.get('scope', 'unknown')}"
        ),
        select,
    )


def resolve_fixture_choice(
    fixtures: list[dict[str, Any]], *, select: Callable[[list[str]], str]
) -> dict[str, Any] | None:
    return _resolve_choice(
        fixtures,
        lambda fixture: (
            f"{fixture.get('fixture_id', '?')}  "
            f"{int(fixture.get('page_count') or 0):,} pages  "
            f"{int(fixture.get('accession_count') or 0):,} accessions  "
            f"{fixture.get('capture_state', 'unknown')}"
        ),
        select,
    )
