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
from edgar_sec.pipelines.document_acquisition.fixture_store.reader import (
    list_fixture_summaries,
)
from edgar_sec.pipelines.document_acquisition.paths import (
    PublishedDocumentPlan,
    discover_document_plans,
    read_published_plan,
    resolve_acquisition_paths,
    resolve_document_planning_paths,
)
from edgar_sec.pipelines.document_acquisition.review_artifacts.analyzer import (
    analyze_review_run,
)
from edgar_sec.pipelines.document_acquisition.run_validation import (
    iter_work_order_rows,
    load_validated_work_order,
)
from edgar_sec.pipelines.document_acquisition.run_state.evidence import (
    list_target_attempts,
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
    active_plan: PublishedDocumentPlan | None = None

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
        return valid

    def label(self) -> str:
        if self.active_plan is None:
            return "Active S6 target plan: none"
        return (
            f"Active S6 target plan: {self.active_plan.plan_id} "
            f"(digest {self.active_plan.manifest['plan_digest']})"
        )

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

    def switch_plan(self) -> None:
        plan = self.choose_plan()
        if plan is not None:
            self.active_plan = plan
            print(f"Active plan set to {plan.plan_id}.")

    def require_plan(self) -> PublishedDocumentPlan | None:
        if self.active_plan is None:
            self.active_plan = self.choose_plan()
        if self.active_plan is None:
            print("Select a validated published S6 plan first.")
        return self.active_plan

    def fixtures(self):
        return list(
            list_fixture_summaries(
                resolve_acquisition_paths(artifacts_root=self.artifacts_root)
            )
        )

    def choose_fixture(self, *, active_plan_only: bool = True) -> str | None:
        plan = self.require_plan() if active_plan_only else None
        fixtures = self.fixtures()
        if plan is not None:
            fixtures = [
                item
                for item in fixtures
                if item.target_plan_id == plan.plan_id
                and item.target_plan_digest == plan.manifest["plan_digest"]
                and item.target_plan_schema_version
                == plan.manifest["target_schema_version"]
            ]
        choices = [
            PickItem(
                str(index),
                f"{item.fixture_id} | {item.case_count} cases | "
                f"plan={item.target_plan_id}",
                item.fixture_id,
            )
            for index, item in enumerate(fixtures, 1)
        ]
        selected = prompt_paginated_choice(choices, prompt_label="Fixture")
        return selected.value if selected is not None else None

    def create_fixture(self) -> None:
        plan = self.require_plan()
        if plan is None:
            return
        fixture_id = prompt_text("New fixture ID").strip()
        if fixture_id:
            cli_main(
                [
                    "fixture",
                    "create",
                    "--fixture",
                    fixture_id,
                    "--plan-id",
                    plan.plan_id,
                    "--artifacts",
                    str(self.artifacts_root),
                ]
            )

    def fill_fixture(self) -> None:
        if self.require_plan() is None:
            return
        fixture_id = self.choose_fixture()
        if fixture_id is None:
            return
        run_id = self.choose_run()
        if run_id is None:
            return
        target_id = self.choose_run_target(run_id)
        if target_id is None:
            return
        attempt_id = self.choose_attempt(run_id, target_id)
        if attempt_id is None:
            return
        try:
            default_limit = _configured_response_byte_limit()
            response_limit = positive_int_type(
                prompt_text("Maximum response bytes", str(default_limit))
                or str(default_limit)
            )
        except (KeyError, TypeError, ValueError) as error:
            print(f"Fixture fill cancelled: invalid response-byte limit ({error}).")
            return
        print(
            f"Retain evidence for fixture={fixture_id}, plan={self.active_plan.plan_id}, "
            f"run={run_id}, target={target_id}, attempt={attempt_id}; "
            f"maximum response bytes={response_limit}."
        )
        if (
            prompt_text("Retain this run's local response evidence? (yes/no)", "no")
            .strip()
            .lower()
            != "yes"
        ):
            print("Fixture fill cancelled; no local evidence was retained.")
            return
        cli_main(
            [
                "fixture",
                "fill",
                "--fixture",
                fixture_id,
                "--run-id",
                run_id,
                "--target-id",
                target_id,
                "--attempt-id",
                attempt_id,
                "--max-response-bytes",
                str(response_limit),
                "--artifacts",
                str(self.artifacts_root),
            ]
        )

    def choose_run(self) -> str | None:
        plan = self.require_plan()
        if plan is None:
            return None
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
                manifest.get("target_plan_id") != plan.plan_id
                or manifest.get("target_plan_digest") != plan.manifest["plan_digest"]
                or manifest.get("target_schema_version")
                != plan.manifest["target_schema_version"]
            ):
                continue
            target_count = manifest.get("target_row_count")
            if isinstance(target_count, bool) or not isinstance(target_count, int):
                target_count = "?"
            items.append(
                PickItem(
                    run_id,
                    f"{run_id} | targets={target_count}",
                    run_id,
                )
            )
        if not items:
            print("No projected acquisition runs match the active S6 plan.")
            return None
        selected = prompt_paginated_choice(items, prompt_label="Acquisition run")
        return str(selected.value) if selected is not None else None

    def choose_run_target(self, run_id: str) -> str | None:
        paths = resolve_acquisition_paths(artifacts_root=self.artifacts_root)
        parts = load_validated_work_order(paths, run_id)
        items = []
        for row in iter_work_order_rows(parts):
            if not row["executable"]:
                continue
            target_id = str(row["target_id"])
            items.append(PickItem(target_id, target_id, target_id))
        if not items:
            print(f"No executable targets are available in run {run_id}.")
            return None
        selected = prompt_paginated_choice(items, prompt_label="Recorded target")
        return str(selected.value) if selected is not None else None

    def choose_attempt(self, run_id: str, target_id: str) -> str | None:
        paths = resolve_acquisition_paths(artifacts_root=self.artifacts_root)
        attempts = list_target_attempts(paths.run_state_path(run_id), target_id)
        items = []
        for index, attempt in enumerate(attempts):
            if attempt.attempt_kind != "document_body":
                continue
            if index > 0 and attempts[index - 1].attempt_kind == "lazy_index":
                continue
            evidence = (
                "body retained"
                if attempt.source_body_relative_path is not None
                else "metadata only"
            )
            items.append(
                PickItem(
                    attempt.attempt_id,
                    f"{attempt.attempt_id} | attempt={attempt.attempt_number} | "
                    f"{attempt.outcome} | {evidence}",
                    attempt.attempt_id,
                )
            )
        if not items:
            print(f"No document-body attempts are recorded for target {target_id}.")
            return None
        selected = prompt_paginated_choice(items, prompt_label="Exact attempt")
        return str(selected.value) if selected is not None else None

    def list_fixtures(self) -> None:
        cli_main(["fixture", "list", "--artifacts", str(self.artifacts_root)])

    def generate_review(self) -> None:
        fixture_id = self.choose_fixture()
        if fixture_id is None:
            return
        args = ["review", "generate", "--fixture", fixture_id]
        for option, label in (
            ("--capture-id", "Capture ID filter"),
            ("--target-id", "Target ID filter"),
            ("--output", "Review output directory"),
        ):
            value = prompt_text(f"{label} (optional)").strip()
            if value:
                args.extend((option, value))
        args.extend(("--artifacts", str(self.artifacts_root)))
        cli_main(args)

    def review_runs(self) -> list[Path]:
        root = resolve_acquisition_paths(
            artifacts_root=self.artifacts_root
        ).review_runs_root
        if not root.exists():
            return []
        directories = sorted(
            (
                item
                for item in root.iterdir()
                if item.is_dir() and not item.name.startswith("diff-")
            ),
            key=lambda item: item.name,
        )
        valid = []
        for directory in directories:
            try:
                analyze_review_run(directory)
            except (OSError, ValueError):
                continue
            valid.append(directory)
        return valid

    def choose_review_run(self) -> Path | None:
        runs = self.review_runs()
        choices = [
            PickItem(str(index), run.name, run) for index, run in enumerate(runs, 1)
        ]
        selected = prompt_paginated_choice(choices, prompt_label="Review run")
        return selected.value if selected is not None else None

    def compare_reviews(self) -> None:
        base = self.choose_review_run()
        new = self.choose_review_run()
        if base is not None and new is not None and base != new:
            cli_main(
                [
                    "review",
                    "compare",
                    "--base",
                    str(base),
                    "--new",
                    str(new),
                    "--artifacts",
                    str(self.artifacts_root),
                ]
            )

    def analyze_reviews(self) -> None:
        remaining = self.review_runs()
        if not remaining:
            print("No validated review runs are available.")
            return
        selected_runs = []
        while remaining:
            choices = [PickItem("__done__", "Finish selection", None)]
            choices.extend(
                PickItem(str(index), run.name, run)
                for index, run in enumerate(remaining, 1)
            )
            selected = prompt_paginated_choice(
                choices, prompt_label="Select review run to analyze"
            )
            if selected is None:
                return
            if selected.key == "__done__":
                break
            selected_runs.append(selected.value)
            remaining = [run for run in remaining if run != selected.value]
        if not selected_runs:
            print("Review analysis cancelled: select at least one validated run.")
            return
        args = ["review", "analyze"]
        for run in selected_runs:
            args.extend(("--run", str(run)))
        args.extend(("--artifacts", str(self.artifacts_root)))
        cli_main(args)


def _action_fixture_review_console() -> None:
    artifacts_root = resolve_acquisition_paths().artifacts_root
    console = _FixtureReviewConsole(artifacts_root)
    run_interactive_menu(
        "Document Acquisition Fixtures & Review Console",
        build_menu(
            menu_action("Select or switch active S6 plan", console.switch_plan),
            menu_action("Create fixture for active S6 plan", console.create_fixture),
            menu_action(
                "Fill fixture from recorded run evidence", console.fill_fixture
            ),
            menu_action("List fixtures deterministically", console.list_fixtures),
            menu_action("Generate offline review artifacts", console.generate_review),
            menu_action("Compare validated review runs", console.compare_reviews),
            menu_action("Analyze review runs (offline)", console.analyze_reviews),
        ),
        before_menu=console.label,
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
