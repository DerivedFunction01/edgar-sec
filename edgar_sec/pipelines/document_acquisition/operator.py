"""Interactive entrypoint for acquisition command tracks."""

from __future__ import annotations

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

MENU_TITLE = "Document Acquisition"


def _action(command: str, track: str) -> MenuAction:
    return menu_action(
        track,
        lambda: report_not_implemented(command),
    )


def _action_project() -> None:
    plan_id = prompt_text("Published S6 target-plan ID").strip()
    if not plan_id:
        print("Projection cancelled.")
        return
    cli_main(["project", "--plan-id", plan_id])


def _action_status() -> None:
    run_id = prompt_text("Run ID (blank lists all runs)").strip()
    args = ["status"]
    if run_id:
        args.extend(("--run-id", run_id))
        target_id = prompt_text("Target ID (optional)").strip()
        if target_id:
            args.extend(("--target-id", target_id))
    cli_main(args)


def _configured_response_byte_limit() -> int:
    settings = resolve_settings(include=("acquisition",))
    return positive_int_type(str(settings["acquisition.max_response_bytes"]))


def _action_run() -> None:
    run_id = prompt_text("Projected S9 run ID").strip()
    if not run_id:
        print("Acquisition cancelled.")
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
        run_id = prompt_text("Recorded acquisition run ID").strip()
        target_id = prompt_text("Recorded target ID").strip()
        attempt_id = prompt_text("Exact retained attempt ID").strip()
        if not all((run_id, target_id, attempt_id)):
            print(
                "Fixture fill cancelled; exact run, target, and attempt are required."
            )
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
        runs = self.review_runs()
        if not runs:
            print("No validated review runs are available.")
            return
        print("Validated review runs: " + ", ".join(run.name for run in runs))
        selected_names = prompt_text(
            "Review run IDs to analyze (comma-separated)", runs[0].name
        ).split(",")
        by_name = {run.name: run for run in runs}
        names = [name.strip() for name in selected_names if name.strip()]
        if (
            not names
            or len(names) != len(set(names))
            or any(name not in by_name for name in names)
        ):
            print("Review analysis cancelled: select unique validated run IDs.")
            return
        args = ["review", "analyze"]
        for name in names:
            args.extend(("--run", str(by_name[name])))
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


def _build_snapshot_menu() -> tuple[MenuAction, ...]:
    return build_menu(
        _action("publish", "Publish snapshot (S11 gate)"),
        _action("snapshot status", "Snapshot status (S11 gate)"),
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
