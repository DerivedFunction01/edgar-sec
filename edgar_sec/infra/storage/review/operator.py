"""Interactive operator console for review artifacts, comparisons, and fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from edgar_sec.foundation.runtime.interactive import (
    PickItem,
    prompt_paginated_choice,
    build_menu,
    menu_action,
    prompt_text,
    run_interactive_menu,
)
from edgar_sec.foundation.runtime.paths import resolve_paths

from .adapter import ReviewAdapter
from .diff import compare_review_runs
from .paths import (
    ReviewPaths,
    is_diff_run_dir,
    new_diff_dir,
    new_review_run_dir,
    review_runs_root,
)


@dataclass(frozen=True, slots=True)
class ReviewMenuConfig:
    """Configuration for the review fixtures and comparison console."""

    adapter: ReviewAdapter
    plan_id: str | None = None
    fixture_id_default: Callable[[dict[str, Any]], str] | None = None
    plans_root: Path | str | None = None
    artifacts_root: Path | str | Callable[[], Path] | None = None
    analyze_action: Callable[[tuple[str, ...]], None] | None = None
    plan_discovery: Callable[[], list[PickItem]] | None = None
    plan_summary: Callable[[Any | None], str] | None = None
    fixture_filter: Callable[[dict[str, Any], Any], bool] | None = None
    fixture_label: Callable[[dict[str, Any]], str] | None = None
    fill_action: Callable[[str, Any, int | None, Path], bool] | None = None
    prompt_limit: bool = True
    prompt_output: bool = True
    prompt_workers: bool = True
    require_active_plan: bool = False
    title: str = "Review Artifacts & Fixtures Console"

    def resolve_root(self) -> Path:
        root = self.artifacts_root
        if callable(root):
            return Path(root()).resolve()
        if root is not None:
            return Path(root).resolve()
        return resolve_paths().artifacts_root


def run_review_menu(config: ReviewMenuConfig) -> int:
    """Run interactive terminal console for review runs and fixtures."""
    root = config.resolve_root()
    adapter = config.adapter
    review_root = review_runs_root(root, adapter.dataset_name)
    session_plan: Any = None

    def _plan_info() -> Any | None:
        nonlocal session_plan
        if session_plan is not None:
            return session_plan
        if config.plan_id:
            session_plan = {
                "plan_id": config.plan_id,
                "scope": "unknown",
                "selected_rows": 0,
            }
            return session_plan
        if config.plan_discovery is not None:
            items = config.plan_discovery()
            if not items:
                return None
            chosen = prompt_paginated_choice(
                items,
                prompt_label="Select plan",
                default=items[0],
            )
            if chosen is not None:
                session_plan = chosen.value
                return session_plan
        elif config.plans_root:
            from edgar_sec.domain.plan.discovery import discover_plans

            plans = discover_plans(config.plans_root)
            if not plans:
                return None
            items = [
                PickItem(key=p.plan_id, label=p.describe(), value=p) for p in plans
            ]
            chosen = prompt_paginated_choice(
                items,
                prompt_label="Select plan",
                default=items[0],
            )
            if chosen is not None:
                session_plan = chosen.value
                return session_plan
        return None

    def _fixture_label(f: dict[str, Any]) -> str:
        if config.fixture_label is not None:
            return config.fixture_label(f)
        fid = f.get("fixture_id", "unknown")
        pages = int(f.get("page_count") or 0)
        accessions = int(f.get("accession_count") or f.get("case_count") or 0)
        state = f.get("capture_state", f"{f.get('capture_count', 0)} captures")
        return f"{fid}  ({pages:,} pages, {accessions:,} accessions, {state})"

    def _fixtures() -> list[dict[str, Any]]:
        fixtures = adapter.list_fixtures(root)
        plan = session_plan
        if config.fixture_filter is not None and plan is not None:
            fixtures = [
                fixture for fixture in fixtures if config.fixture_filter(fixture, plan)
            ]
        return fixtures

    def _limit_from_plan(plan: dict[str, Any]) -> int | None:
        if not config.prompt_limit:
            return None
        scope = plan.get("scope", "unknown")
        rows = plan.get("selected_rows")
        if scope == "policy" and rows:
            prompt = (
                f"Plan scope is 'policy' (curated to {rows} accessions). "
                f"Limit accessions [all {rows}]"
            )
            default = ""
        elif scope == "deterministic" and rows:
            prompt = (
                f"Plan scope is 'deterministic' ({rows} locators). "
                f"Limit accessions [500]"
            )
            default = "500"
        else:
            prompt = "Limit accessions (blank for all)"
            default = ""
        raw = prompt_text(prompt, default).strip()
        if raw == "" or raw.lower() == "all":
            return None
        return (
            int(raw) if raw.isdigit() else (int(default) if default.isdigit() else None)
        )

    def _action_create() -> None:
        plan = _plan_info()
        if plan is None:
            print("No plans available; publish a plan first.")
            return
        default_fid = (
            config.fixture_id_default(plan)
            if config.fixture_id_default is not None
            else f"fix-{plan['plan_id'][:8]}"
        )
        fixture_id = prompt_text("Fixture ID", default_fid).strip()
        if not fixture_id:
            return
        limit = _limit_from_plan(plan)
        adapter.create_fixture(
            fixture_id, plan["plan_id"], limit=limit, artifacts_root=root
        )
        print(f"Fixture '{fixture_id}' created from plan '{plan['plan_id']}'.")

    def _action_fill() -> None:
        plan = _plan_info() if config.require_active_plan else None
        fixtures = _fixtures()
        if not fixtures:
            print("No fixtures found to extend.")
            return
        items = [
            PickItem(key=f["fixture_id"], label=_fixture_label(f), value=f)
            for f in fixtures
        ]
        chosen = prompt_paginated_choice(items, prompt_label="Select fixture to extend")
        if chosen is None:
            return
        fixture_id = chosen.key

        if plan is None:
            val = chosen.value if isinstance(chosen.value, dict) else {}
            if "target_plan_id" in val:
                plan = {
                    "plan_id": val["target_plan_id"],
                    "plan_digest": val.get("target_plan_digest", ""),
                    "target_plan_schema_version": val.get(
                        "target_plan_schema_version", 1
                    ),
                    "scope": "unknown",
                    "selected_rows": val.get("selected_rows", 0),
                }
            else:
                plan = _plan_info()
        if plan is None:
            print("No plans available; publish a plan first.")
            return
        limit = _limit_from_plan(plan)
        if config.fill_action is None:
            result = adapter.fill_fixture(
                fixture_id, plan["plan_id"], limit=limit, artifacts_root=root
            )
        else:
            result = config.fill_action(fixture_id, plan, limit, root)
        if result is not False:
            print(f"Fixture '{fixture_id}' extended from plan '{plan['plan_id']}'.")

    def _action_list() -> None:
        fixtures = adapter.list_fixtures(root)
        if not fixtures:
            print("No fixtures found.")
            return
        print(f"\nDiscovered {len(fixtures)} fixture(s):")
        for f in fixtures:
            fid = f.get("fixture_id", "unknown")
            cases = f.get("case_count", f.get("total_cases", ""))
            print(f"  * {fid:<24} ({cases} cases)")

    def _action_generate() -> None:
        if config.require_active_plan and _plan_info() is None:
            print("No plans available; publish a plan first.")
            return
        fixtures = _fixtures()
        if not fixtures:
            print("No fixtures found to review.")
            return
        items = [
            PickItem(key=f["fixture_id"], label=_fixture_label(f), value=f)
            for f in fixtures
        ]
        chosen = prompt_paginated_choice(items, prompt_label="Select fixture to review")
        if chosen is None:
            return
        fixture_id = chosen.key

        output_dir = new_review_run_dir(review_root)
        if config.prompt_output:
            default_out = f"auto {output_dir.name}"
            out_raw = prompt_text(f"Output run [{default_out}]", "").strip()
            if out_raw:
                output_dir = Path(out_raw)
        limit = None
        if config.prompt_limit:
            limit_raw = prompt_text("Limit cases (blank for all)", "").strip()
            limit = int(limit_raw) if limit_raw.isdigit() else None
        workers = None
        if config.prompt_workers:
            workers_raw = prompt_text("Workers (blank for auto)", "").strip()
            workers = int(workers_raw) if workers_raw.isdigit() else None
        adapter.build_review_artifacts(
            fixture_id=fixture_id,
            output_dir=output_dir,
            limit=limit,
            workers=workers,
            artifacts_root=root,
        )
        print(f"Review artifacts written to: {output_dir}")

    def _action_compare() -> None:
        runs: list[Path] = []
        if review_root.is_dir():
            runs = sorted(
                [
                    p
                    for p in review_root.iterdir()
                    if p.is_dir() and not is_diff_run_dir(p)
                ],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        if len(runs) == 0:
            print(
                f"No review runs found under {review_root}. "
                "Run option 4 to generate a review run first."
            )
            return
        if len(runs) == 1:
            print(
                f"Only 1 review run found ({runs[0].name}). "
                "Comparison requires at least two runs; "
                "run option 4 to generate a candidate review run first."
            )
            return
        items = [
            PickItem(
                key=r.name, label=r.name + (" (latest)" if i == 0 else ""), value=r
            )
            for i, r in enumerate(runs)
        ]
        base_chosen = prompt_paginated_choice(
            items,
            default=runs[-2].name if len(runs) >= 2 else items[0].key,
            prompt_label="Base review run (previous baseline)",
        )
        if base_chosen is None:
            return
        new_chosen = prompt_paginated_choice(
            items,
            default=runs[0].name,
            prompt_label="New review run (candidate)",
        )
        if new_chosen is None:
            return
        base_dir = base_chosen.value
        new_dir = new_chosen.value
        diff_dir = new_diff_dir(review_root)
        compare_review_runs(
            base_dir=base_dir, new_dir=new_dir, output_dir=diff_dir, adapter=adapter
        )
        print(ReviewPaths(diff_dir).summary_file.read_text(encoding="utf-8"))

    def _action_analyze() -> None:
        if config.analyze_action is None:
            return
        runs = []
        if review_root.is_dir():
            runs = sorted(
                [
                    p
                    for p in review_root.iterdir()
                    if p.is_dir() and not is_diff_run_dir(p)
                ],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        if not runs:
            print(f"No review runs found under {review_root}.")
            return
        print("\nAvailable review runs:")
        for index, run in enumerate(runs, start=1):
            print(f"  {index}. {run.name}")
        selection = prompt_text(
            "Run numbers (comma-separated), 'all', or blank to cancel"
        ).strip()
        if not selection:
            return
        if selection.lower() == "all":
            selected = runs
        else:
            indices = []
            for value in selection.split(","):
                token = value.strip()
                if not token.isdigit() or not 1 <= int(token) <= len(runs):
                    print("Invalid review-run selection; analysis cancelled.")
                    return
                index = int(token) - 1
                if index not in indices:
                    indices.append(index)
            selected = [runs[index] for index in indices]
        config.analyze_action(tuple(run.name for run in selected))

    def _action_switch_plan() -> None:
        nonlocal session_plan
        if config.plan_discovery is not None:
            items = config.plan_discovery()
            if not items:
                print("No published plans discovered.")
                return
            chosen = prompt_paginated_choice(
                items,
                prompt_label="Select active plan",
                default=items[0],
            )
            if chosen is not None:
                session_plan = chosen.value
                print(f"Active plan switched to {session_plan['plan_id']}")
            return
        if not config.plans_root:
            print("No plans directory configured for this console.")
            return
        from edgar_sec.domain.plan.discovery import discover_plans

        plans = discover_plans(config.plans_root)
        if not plans:
            print("No published plans discovered.")
            return
        items = [PickItem(key=p.plan_id, label=p.describe(), value=p) for p in plans]
        chosen = prompt_paginated_choice(
            items,
            prompt_label="Select active plan",
            default=items[0],
        )
        if chosen is not None:
            session_plan = chosen.value
            print(f"Active plan switched to {session_plan['plan_id']}")

    actions = [
        menu_action("Create fixture from a published plan", _action_create),
        menu_action("Fill a discovered fixture from a plan", _action_fill),
        menu_action("List discovered fixtures", _action_list),
        menu_action("Generate parser review artifacts from fixture", _action_generate),
        menu_action("Compare two review runs (diff & summary)", _action_compare),
    ]
    if config.analyze_action is not None:
        actions.append(menu_action("Analyze review runs (offline)", _action_analyze))
    if (config.plans_root or config.plan_discovery is not None) and (
        config.require_active_plan or config.plan_summary is not None
    ):
        actions.append(menu_action("Switch active plan", _action_switch_plan, key="s"))

    menu = build_menu(*actions)

    before_menu = (
        (lambda: config.plan_summary(session_plan))
        if config.plan_summary is not None
        else None
    )
    return run_interactive_menu(
        config.title, menu, exit_key="0", before_menu=before_menu
    )
