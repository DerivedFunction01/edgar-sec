"""Interactive entrypoint for acquisition command tracks."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from edgar_sec.foundation.runtime.interactive import (
    MenuAction,
    PickItem,
    build_menu,
    menu_action,
    operator_entrypoint,
    prompt_paginated_choice,
    prompt_text,
    run_interactive_menu,
)
from edgar_sec.foundation.runtime.settings import resolve_settings
from edgar_sec.foundation.runtime.settings.validators import positive_int_type
from edgar_sec.pipelines.document_acquisition.cli import (
    main as cli_main,
    report_not_implemented,
)
from edgar_sec.pipelines.document_acquisition.commands.status import (
    discover_run_ids,
)
from edgar_sec.pipelines.document_acquisition.paths import (
    PublishedDocumentPlan,
    discover_document_plans,
    read_published_plan,
    resolve_acquisition_paths,
    resolve_document_planning_paths,
)
from edgar_sec.pipelines.document_acquisition.run_validation import (
    iter_work_order_rows,
    load_validated_work_order,
)
from edgar_sec.pipelines.document_acquisition.run_state.evidence import (
    list_target_attempts,
)
from edgar_sec.pipelines.document_acquisition.run_state.store import (
    inspect_run_state,
)

MENU_TITLE = "Document Acquisition"


def _action(command: str, track: str) -> MenuAction:
    return menu_action(
        track,
        lambda: report_not_implemented(command),
    )


def _action_project() -> None:
    plan = _select_target_plan()
    if plan is None:
        print("Projection cancelled.")
        return
    cli_main(["project", "--plan-id", plan.plan_id])


def _select_target_plan() -> PublishedDocumentPlan | None:
    console = _FixtureReviewConsole(resolve_acquisition_paths().artifacts_root)
    return console.choose_plan()


def _run_items(*, include_all: bool = False) -> list[PickItem]:
    paths = resolve_acquisition_paths()
    run_ids = discover_run_ids(paths)
    items = []
    if include_all:
        items.append(PickItem("all", "All acquisition runs", ""))
    items.extend(PickItem(run_id, run_id, run_id) for run_id in run_ids)
    return items


def _choose_run_id(prompt_label: str) -> str | None:
    items = _run_items()
    if not items:
        print("No acquisition runs found; project a target plan first.")
        return None
    selected = prompt_paginated_choice(items, prompt_label=prompt_label)
    return str(selected.value) if selected is not None else None


def _target_items(run_id: str) -> list[PickItem]:
    paths = resolve_acquisition_paths()
    parts = load_validated_work_order(paths, run_id)
    items = [PickItem("summary", "Run summary (no target filter)", "")]
    for row in iter_work_order_rows(parts):
        target_id = str(row["target_id"])
        label = target_id
        if not row["executable"]:
            label += f" | skipped: {row['skip_reason']}"
        items.append(PickItem(target_id, label, target_id))
    return items


def _action_status() -> None:
    items = _run_items(include_all=True)
    if len(items) == 1 and items[0].key == "all":
        print("No acquisition runs found.")
        return
    selected = prompt_paginated_choice(items, prompt_label="Acquisition run")
    if selected is None:
        return
    args = ["status"]
    run_id = str(selected.value)
    if run_id:
        target = prompt_paginated_choice(
            _target_items(run_id), prompt_label="Target status"
        )
        if target is None:
            return
        args.extend(("--run-id", run_id))
        if target.value:
            args.extend(("--target-id", str(target.value)))
    cli_main(args)


def _configured_response_byte_limit() -> int:
    settings = resolve_settings(include=("acquisition",))
    return positive_int_type(str(settings["acquisition.max_response_bytes"]))


def _action_run() -> None:
    run_id = _choose_run_id("Projected acquisition run")
    if run_id is None:
        return
    try:
        default_limit = _configured_response_byte_limit()
    except (KeyError, TypeError, ValueError) as error:
        print(
            f"Acquisition cancelled: invalid configured response-byte limit ({error})."
        )
        return
    response_limit = prompt_text(
        "Maximum decoded response bytes", str(default_limit)
    ).strip()
    try:
        effective_limit = positive_int_type(response_limit or str(default_limit))
    except ValueError:
        print("Acquisition cancelled: enter a positive response-byte limit.")
        return
    retry = (
        prompt_text(
            "Retry eligible failed acquisition/processing targets? (yes/no)", "no"
        )
        .strip()
        .lower()
    )
    if retry not in {"yes", "no"}:
        print("Acquisition cancelled: answer yes or no for retry selection.")
        return
    retain = (
        prompt_text("Retain raw response evidence? (yes/no)", "no").strip().lower()
        or "no"
    )
    if retain not in {"yes", "no"}:
        print("Acquisition cancelled: answer yes or no for response retention.")
        return
    confirm = (
        prompt_text("Allow live SEC network access? (yes/no)", "no").strip().lower()
    )
    if confirm != "yes":
        print("Acquisition cancelled; no network request was made.")
        return
    args = [
        "run",
        "--run-id",
        run_id,
        "--max-response-bytes",
        str(effective_limit),
    ]
    if retry == "yes":
        args.append("--retry-failures")
    if retain == "yes":
        args.append("--retain-response-evidence")
    cli_main(args)


@dataclass
class _FixtureReviewConsole:
    artifacts_root: Path

    @property
    def planning_paths(self):
        return resolve_document_planning_paths(artifacts_root=self.artifacts_root)

    def plans(self) -> list[PublishedDocumentPlan]:
        valid = []
        for discovery in discover_document_plans(self.planning_paths):
            if discovery.plan is None:
                continue
            try:
                valid.append(
                    read_published_plan(discovery.plan_id, self.planning_paths)
                )
            except (OSError, ValueError):
                continue
        return sorted(valid, key=lambda plan: plan.plan_id)

    def plan_summary(self, plan: dict | None) -> str:
        if plan is None:
            return "Active S6 target plan: none"
        return (
            f"Active S6 target plan: {plan['plan_id']} (digest {plan['plan_digest']})"
        )

    def plan_items(self) -> list[PickItem]:
        items = []
        for plan in self.plans():
            manifest = plan.manifest
            value = {
                "plan_id": plan.plan_id,
                "plan_digest": manifest["plan_digest"],
                "target_plan_schema_version": manifest["target_schema_version"],
                "scope": "unknown",
                "selected_rows": manifest["target_row_count"],
            }
            items.append(
                PickItem(
                    key=plan.plan_id,
                    label=(
                        f"{plan.plan_id} | rows={manifest['target_row_count']} | "
                        f"{manifest['plan_digest']}"
                    ),
                    value=value,
                )
            )
        return items

    def choose_plan(self) -> PublishedDocumentPlan | None:
        plans = self.plans()
        choices = [
            PickItem(
                str(index),
                f"{plan.plan_id} | rows={plan.manifest['target_row_count']} | "
                f"{plan.manifest['plan_digest']}",
                plan,
            )
            for index, plan in enumerate(plans, 1)
        ]
        selected = prompt_paginated_choice(choices, prompt_label="Published S6 plan")
        return selected.value if selected is not None else None

    def fixture_matches_plan(self, fixture: dict, plan: dict) -> bool:
        return (
            fixture.get("target_plan_id") == plan["plan_id"]
            and fixture.get("target_plan_digest") == plan["plan_digest"]
            and fixture.get("target_plan_schema_version")
            == plan["target_plan_schema_version"]
        )

    @staticmethod
    def fixture_label(fixture: dict) -> str:
        return (
            f"{fixture['fixture_id']} | cases={fixture['case_count']} | "
            f"captures={fixture['capture_count']}"
        )

    def choose_run(self, plan: dict) -> str | None:
        paths = resolve_acquisition_paths(artifacts_root=self.artifacts_root)
        items = []
        for run_id in discover_run_ids(paths):
            manifest_path = paths.run_manifest_path(run_id)
            if manifest_path.is_symlink() or not manifest_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(manifest, dict):
                continue
            if (
                manifest.get("target_plan_id") != plan["plan_id"]
                or manifest.get("target_plan_digest") != plan["plan_digest"]
                or manifest.get("target_schema_version")
                != plan["target_plan_schema_version"]
            ):
                continue
            try:
                load_validated_work_order(paths, run_id)
            except (OSError, RuntimeError, ValueError):
                continue
            report = inspect_run_state(
                run_id,
                database_path=paths.run_state_path(run_id),
                lock_path=paths.run_lock_path(run_id),
            )
            acquired_count = report.target_counts.get("acquired", 0)
            if report.state == "invalid" or report.active_lock or not acquired_count:
                continue
            target_count = manifest.get("target_row_count")
            if isinstance(target_count, bool) or not isinstance(target_count, int):
                target_count = "?"
            items.append(
                PickItem(
                    run_id,
                    f"{run_id} | targets={target_count} | acquired={acquired_count}",
                    run_id,
                )
            )
        if not items:
            print("No projected acquisition runs match the active S6 plan.")
            return None
        selected = prompt_paginated_choice(items, prompt_label="Acquisition run")
        return str(selected.value) if selected is not None else None

    def fill_fixture(
        self, fixture_id: str, plan: dict, _limit: int | None, _root: Path
    ) -> bool:
        run_id = self.choose_run(plan)
        if run_id is None:
            return False
        return (
            cli_main(
                [
                    "fixture",
                    "fill",
                    "--fixture",
                    fixture_id,
                    "--run-id",
                    run_id,
                    "--artifacts",
                    str(self.artifacts_root),
                ]
            )
            == 0
        )

    def analyze_reviews(self, run_ids: tuple[str, ...]) -> None:
        args = ["review", "analyze"]
        for run_id in run_ids:
            args.extend(("--run", run_id))
        args.extend(("--artifacts", str(self.artifacts_root)))
        cli_main(args)


def _action_fixture_review_console() -> None:
    from edgar_sec.infra.storage.review.operator import (
        ReviewMenuConfig,
        run_review_menu,
    )
    from edgar_sec.pipelines.document_acquisition.review_artifacts.adapter import (
        AcquisitionReviewAdapter,
    )

    artifacts_root = resolve_acquisition_paths().artifacts_root
    console = _FixtureReviewConsole(artifacts_root)
    run_review_menu(
        ReviewMenuConfig(
            adapter=AcquisitionReviewAdapter(),
            artifacts_root=artifacts_root,
            analyze_action=console.analyze_reviews,
            plan_discovery=console.plan_items,
            plan_summary=console.plan_summary,
            fixture_filter=console.fixture_matches_plan,
            fixture_label=console.fixture_label,
            fill_action=console.fill_fixture,
            prompt_limit=False,
            prompt_output=False,
            prompt_workers=False,
            require_active_plan=True,
            title="Document Acquisition Fixtures & Review Console",
        )
    )


def _action_publish_run() -> None:
    paths = resolve_acquisition_paths()
    run_ids = discover_run_ids(paths)
    if not run_ids:
        print("No acquisition runs found.")
        return
    items = [PickItem(run_id, run_id, run_id) for run_id in run_ids]
    chosen = prompt_paginated_choice(
        items, prompt_label="Select completed run to publish"
    )
    if chosen is None:
        return
    branch = prompt_text("Destination DAG branch", "main").strip() or "main"
    cli_main(
        [
            "publish",
            "--run-id",
            str(chosen.value),
            "--branch",
            branch,
            "--artifacts",
            str(paths.artifacts_root),
        ]
    )


def _action_inspect_snapshot() -> None:
    paths = resolve_acquisition_paths()
    branch = prompt_text("DAG branch to inspect", "main").strip() or "main"
    cli_main(
        [
            "snapshot",
            "status",
            "--branch",
            branch,
            "--artifacts",
            str(paths.artifacts_root),
        ]
    )


def _build_snapshot_menu() -> tuple[MenuAction, ...]:
    return build_menu(
        menu_action("Publish snapshot (S11 gate)", _action_publish_run),
        menu_action("Snapshot status (S11 gate)", _action_inspect_snapshot),
    )


def _action_snapshot_console() -> None:
    run_interactive_menu(
        "Document Acquisition Snapshot Console",
        _build_snapshot_menu(),
    )


def build_operator_menu() -> tuple[MenuAction, ...]:
    return build_menu(
        menu_action("Project a target plan", _action_project),
        menu_action("Inspect acquisition runs", _action_status),
        menu_action("Run acquisition and process acquired bodies", _action_run),
        menu_action(
            "Snapshot console (publish, status; S11 gate)",
            _action_snapshot_console,
            key="p",
        ),
        menu_action(
            "Fixtures and review console (plan-pinned fixtures and review)",
            _action_fixture_review_console,
            key="f",
        ),
    )


def main(argv: list[str] | None = None) -> int:
    return operator_entrypoint(MENU_TITLE, build_operator_menu(), cli_main, argv)


if __name__ == "__main__":
    sys.exit(main())
