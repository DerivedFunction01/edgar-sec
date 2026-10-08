"""Interactive operator console for review artifacts, comparisons, and fixtures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from edgar_sec.foundation.runtime.interactive import (
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


def run_review_menu(
    adapter: ReviewAdapter,
    artifacts_root: Path | str | None = None,
) -> int:
    """Run interactive terminal console for review runs and fixtures."""
    root = Path(artifacts_root) if artifacts_root else resolve_paths().artifacts_root
    dataset = adapter.dataset_name

    def _action_create() -> None:
        fixture_id = prompt_text("Fixture ID").strip()
        if not fixture_id:
            return
        plan_id = prompt_text("Catalog plan ID").strip()
        if not plan_id:
            return
        limit_raw = prompt_text("Limit accessions (blank for all)").strip()
        limit = int(limit_raw) if limit_raw.isdigit() else None
        adapter.create_fixture(fixture_id, plan_id, limit=limit, artifacts_root=root)

    def _action_fill() -> None:
        fixtures = adapter.list_fixtures(root)
        if not fixtures:
            print("No fixtures found to extend.")
            return
        print("Available fixtures:")
        for idx, f in enumerate(fixtures, start=1):
            fid = f.get("fixture_id", "unknown")
            print(f"  {idx}. {fid}")
        choice_raw = prompt_text("Select fixture number or ID").strip()
        if not choice_raw:
            return
        if choice_raw.isdigit() and 1 <= int(choice_raw) <= len(fixtures):
            fixture_id = str(fixtures[int(choice_raw) - 1].get("fixture_id", ""))
        else:
            fixture_id = choice_raw

        plan_id = prompt_text("Catalog plan ID to fill from").strip()
        if not plan_id:
            return
        limit_raw = prompt_text("Limit accessions (blank for all)").strip()
        limit = int(limit_raw) if limit_raw.isdigit() else None
        adapter.fill_fixture(fixture_id, plan_id, limit=limit, artifacts_root=root)

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
        print("Available fixtures:")
        for idx, f in enumerate(fixtures, start=1):
            fid = f.get("fixture_id", "unknown")
            print(f"  {idx}. {fid}")
        choice_raw = prompt_text("Select fixture number or ID").strip()
        if not choice_raw:
            return
        if choice_raw.isdigit() and 1 <= int(choice_raw) <= len(fixtures):
            fixture_id = str(fixtures[int(choice_raw) - 1].get("fixture_id", ""))
        else:
            fixture_id = choice_raw

        out_raw = prompt_text("Output directory (blank for auto-derived)").strip()
        review_root = review_runs_root(root, dataset)
        output_dir = Path(out_raw) if out_raw else new_review_run_dir(review_root)
        limit_raw = prompt_text("Limit cases (blank for all)").strip()
        limit = int(limit_raw) if limit_raw.isdigit() else None
        workers_raw = prompt_text("Workers (blank for default)").strip()
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
        review_root = review_runs_root(root, dataset)
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
        if len(runs) >= 2:
            print("Recent review runs:")
            for idx, r in enumerate(runs[:8], start=1):
                print(f"  {idx}. {r.name}")

        base_raw = prompt_text("Base review run directory or number").strip()
        if not base_raw:
            return
        if base_raw.isdigit() and 1 <= int(base_raw) <= len(runs):
            base_dir = runs[int(base_raw) - 1]
        else:
            base_dir = Path(base_raw)

        new_raw = prompt_text("New review run directory or number").strip()
        if not new_raw:
            return
        if new_raw.isdigit() and 1 <= int(new_raw) <= len(runs):
            new_dir = runs[int(new_raw) - 1]
        else:
            new_dir = Path(new_raw)

        diff_dir = new_diff_dir(review_root)
        compare_review_runs(
            base_dir=base_dir,
            new_dir=new_dir,
            output_dir=diff_dir,
            adapter=adapter,
        )
        print(ReviewPaths(diff_dir).summary_file.read_text(encoding="utf-8"))

    menu = build_menu(
        menu_action("Create fixture from a published catalog plan", _action_create),
        menu_action("Fill a discovered fixture from a catalog plan", _action_fill),
        menu_action("List discovered fixtures", _action_list),
        menu_action("Generate parser review artifacts from fixture", _action_generate),
        menu_action("Compare two review runs (diff & summary report)", _action_compare),
    )

    title = f"{dataset.replace('_', ' ').title()} Fixtures & Review Console"
    return run_interactive_menu(title, menu, exit_key="0")
