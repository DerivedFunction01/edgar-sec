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
    plans_root: Path | str | None = None
    artifacts_root: Path | str | Callable[[], Path] | None = None
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
        if config.plans_root:
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
        fid = f.get("fixture_id", "unknown")
        pages = int(f.get("page_count") or 0)
        accessions = int(f.get("accession_count") or 0)
        state = f.get("capture_state", "unknown")
        return f"{fid}  ({pages:,} pages, {accessions:,} accessions, {state})"

    def _limit_from_plan(plan: dict[str, Any]) -> int | None:
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
        default_fid = f"fix-{plan['plan_id'][:8]}"
        fixture_id = prompt_text("Fixture ID", default_fid).strip()
        if not fixture_id:
            return
        limit = _limit_from_plan(plan)
        adapter.create_fixture(
            fixture_id, plan["plan_id"], limit=limit, artifacts_root=root
        )
        print(f"Fixture '{fixture_id}' created from plan '{plan['plan_id']}'.")

    def _action_fill() -> None:
        fixtures = adapter.list_fixtures(root)
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

        plan = _plan_info()
        if plan is None:
            print("No plans available; publish a plan first.")
            return
        limit = _limit_from_plan(plan)
        adapter.fill_fixture(
            fixture_id, plan["plan_id"], limit=limit, artifacts_root=root
        )
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
        fixtures = adapter.list_fixtures(root)
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

        default_out = f"auto {new_review_run_dir(review_root).name}"
        out_raw = prompt_text(f"Output run [{default_out}]", "").strip()
        output_dir = Path(out_raw) if out_raw else new_review_run_dir(review_root)
        limit_raw = prompt_text("Limit cases (blank for all)", "").strip()
        limit = int(limit_raw) if limit_raw.isdigit() else None
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

    def _action_switch_plan() -> None:
        nonlocal session_plan
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
    if config.plans_root:
        actions.append(menu_action("Switch active plan", _action_switch_plan, key="s"))

    menu = build_menu(*actions)

    title = (
        f"{adapter.dataset_name.replace('_', ' ').title()} Fixtures & Review Console"
    )
    return run_interactive_menu(title, menu, exit_key="0")
