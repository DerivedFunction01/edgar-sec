"""Discovery-driven operator for document inventory snapshots, DAG, and review."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from edgar_sec.foundation.runtime.interactive import (
    MenuAction,
    PickItem,
    build_menu,
    menu_action,
    operator_entrypoint,
    prompt_paginated_choice,
    prompt_text,
)
from edgar_sec.foundation.runtime.paths import resolve_paths
from edgar_sec.pipelines.document_inventory.cli import main as cli_main
from edgar_sec.pipelines.document_inventory.commands.query import cmd_query
from edgar_sec.pipelines.document_inventory.discovery import discover_plans

MENU_TITLE = "Document Inventory"


def _root() -> str:
    return str(resolve_paths().artifacts_root)


def _action_query() -> None:
    accession = prompt_text(
        "Accession number (or press enter to query by form/cik)", ""
    ).strip()
    if accession:
        cmd_query(
            argparse.Namespace(
                accession=accession,
                form=None,
                filing_cik=None,
                source_cik=None,
                limit=None,
                artifacts_root=_root(),
                json=False,
            )
        )
        return
    form = prompt_text("Filing form (or press enter to skip)", "").strip()
    filing_cik = prompt_text(
        "Canonical filing CIK (or press enter to skip)", ""
    ).strip()
    source_cik = prompt_text(
        "Discovery source CIK (or press enter to skip)", ""
    ).strip()
    limit_str = prompt_text("Limit results (default 20)", "20").strip()
    limit = int(limit_str) if limit_str.isdigit() else 20
    cmd_query(
        argparse.Namespace(
            accession=None,
            form=form or None,
            filing_cik=filing_cik or None,
            source_cik=source_cik or None,
            limit=limit,
            artifacts_root=_root(),
            json=False,
        )
    )


def _action_build() -> None:
    plans = discover_plans(_root())
    if not plans:
        print(
            "No published catalog plans were discovered; publish a plan before building an inventory snapshot."
        )
        return
    items = [
        PickItem(
            key=str(p.get("plan_id", "?")),
            label=(
                f"{p.get('plan_id', '?')}  catalog {p.get('catalog_id', '?')}  "
                f"{p.get('scope', 'unknown')}"
            ),
            value=p,
        )
        for p in plans
    ]
    chosen = prompt_paginated_choice(
        items,
        prompt_label="Select catalog plan",
        default=items[0],
    )
    if chosen is None:
        print("Plan selection cancelled.")
        return
    plan_id = str(chosen.value["plan_id"])
    from edgar_sec.pipelines.document_inventory.snapshot.builder import build_inventory

    pub = build_inventory(plan_id, artifacts_root=Path(_root()))
    if pub.was_published and pub.snapshot:
        print(f"Snapshot published successfully: {pub.snapshot.snapshot_id}")
    elif pub.was_no_op:
        print("Snapshot is already up to date (no-op).")
    else:
        print(f"Snapshot build failed: {pub.reason}")


def _action_dag() -> None:
    from edgar_sec.infra.storage.dag.menu import DAGMenuConfig, run_dag_menu
    from edgar_sec.pipelines.document_inventory.paths import InventoryPaths
    from edgar_sec.pipelines.document_inventory.snapshot.specs import (
        INVENTORY_RELATIONS,
    )

    config = DAGMenuConfig(
        snapshots_root=lambda: InventoryPaths(Path(_root())).snapshots_root,
        title="Document Inventory Snapshot DAG Console",
        specs=INVENTORY_RELATIONS,
        publish_action=_action_build,
        publish_label="Build inventory snapshot from published plan",
    )
    run_dag_menu(config)


def _action_distrib() -> None:
    from edgar_sec.infra.distribution.menu import DistribMenuConfig, run_distrib_menu
    from .distribution_adapter import InventoryDistributionAdapter
    from .paths import resolve_filing_catalog_paths

    plans_root = resolve_filing_catalog_paths(_root()).plans_root
    adapter = InventoryDistributionAdapter(artifacts_root=Path(_root()))
    config = DistribMenuConfig(
        adapter=adapter,
        plans_root=plans_root,
        title="Document Inventory Worker Distribution",
    )
    run_distrib_menu(config)


def _action_review() -> None:
    from edgar_sec.infra.storage.review.operator import (
        ReviewMenuConfig,
        run_review_menu,
    )
    from .paths import resolve_filing_catalog_paths
    from .review_adapter import InventoryReviewAdapter

    plans_root = resolve_filing_catalog_paths(_root()).plans_root
    run_review_menu(
        ReviewMenuConfig(
            adapter=InventoryReviewAdapter(),
            plans_root=plans_root,
            artifacts_root=Path(_root()),
            title="Document Inventory Fixtures & Review Console",
        )
    )


def build_operator_menu() -> tuple[MenuAction, ...]:
    return build_menu(
        menu_action("Query document inventory", _action_query),
        menu_action(
            "Worker distribution console (export, worker, import, commands)",
            _action_distrib,
            key="d",
        ),
        menu_action(
            "Snapshot DAG console (build/publish, switch current, inspect, branches, tags)",
            _action_dag,
            key="p",
        ),
        menu_action(
            "Fixtures and review console (create, fill, list, generate, compare)",
            _action_review,
            key="f",
        ),
    )


def main(argv: list[str] | None = None) -> int:
    return operator_entrypoint(MENU_TITLE, build_operator_menu(), cli_main, argv)


if __name__ == "__main__":
    sys.exit(main())
