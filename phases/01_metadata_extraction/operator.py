"""Interactive Phase 1 operator UI."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm

from defs.runtime.artifacts import (
    get_current_snapshot_pointer,
    list_snapshots,
    update_current_snapshot_pointer,
)
from defs.runtime.cli import coalesce
from defs.runtime.interactive import ExtraAction, InteractivePhase, run_interactive
from defs.runtime.progress import make_merge_progress_callback, make_tqdm_callback
from defs.storage import load_json

from .core import (
    DEFAULT_ARTIFACTS,
    PROJECT_CONFIG_DEFAULT_PATH,
    RunOptions,
    artifacts_root,
    build_plan,
    default_user_agent,
    discover_base_metadata_manifests,
    discover_source_manifests,
    get_status,
    load_plan,
    merge,
    merge_one_partition,
    preview_sample,
    refresh_company_tickers,
    run_partition_with_automerge,
)
from .core.merge import MergeError


def options_from_args(args, project_config) -> RunOptions:
    options = RunOptions(
        input_path=coalesce(
            args.input, project_config.input_path, RunOptions.input_path
        ),
        artifacts_dir=coalesce(
            args.artifacts, project_config.artifacts_dir, RunOptions.artifacts_dir
        ),
        chunk_size=coalesce(
            args.chunk_size, project_config.chunk_size, RunOptions.chunk_size
        ),
        partition_count=coalesce(
            getattr(args, "partition_count", None),
            project_config.partition_count,
            RunOptions.partition_count,
        ),
        partition_id=getattr(args, "partition_id", None),
        storage_format=coalesce(
            args.storage_format,
            project_config.storage_format,
            RunOptions.storage_format,
        ),
        chunk_id=args.chunk_id,
        workers=coalesce(args.workers, project_config.workers, RunOptions.workers),
        timeout_s=coalesce(
            args.timeout, project_config.timeout_s, RunOptions.timeout_s
        ),
        max_retries=coalesce(
            args.max_retries, project_config.max_retries, RunOptions.max_retries
        ),
        rate_limit_rps=coalesce(
            args.rate_limit, project_config.rate_limit_rps, RunOptions.rate_limit_rps
        ),
        user_agent=(
            args.user_agent
            if getattr(args, "user_agent", None) is not None
            else (project_config.user_agent or default_user_agent())
        ),
        cache_dir=coalesce(args.cache_dir, project_config.cache_dir, ""),
        max_failure_attempts=coalesce(
            args.max_failure_attempts,
            project_config.max_failure_attempts,
            RunOptions.max_failure_attempts,
        ),
        ignore_failure_history=getattr(args, "ignore_failure_history", False),
        limit=coalesce(args.limit, project_config.limit, RunOptions.limit),
        log_level=args.log_level,
        run_id=args.run_id,
        source_manifest=getattr(args, "source_manifest", None),
        base_metadata_manifest=getattr(args, "base_metadata_manifest", None),
        augmentation=bool(getattr(args, "augmentation", False)),
    )
    options.workers = options.effective_workers()
    return options


def print_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def partition_command(options: RunOptions, partition_id: int) -> str:
    agent = options.user_agent or "$SEC_USER_AGENT"
    storage = (
        f" --storage-format {options.storage_format}"
        if options.storage_format != "parquet"
        else ""
    )
    return (
        f".venv/bin/python -m phases.01_metadata_extraction.cli run"
        f" --config {PROJECT_CONFIG_DEFAULT_PATH} --partition-id {partition_id}"
        f" --input '{options.input_path}' --artifacts '{options.artifacts_dir}'"
        f" --source-manifest '{options.source_manifest or ''}'"
        f" --base-metadata-manifest '{options.base_metadata_manifest or ''}'"
        f" {'--augmentation' if options.augmentation else ''}"
        f" --workers {options.effective_workers()} --rate-limit {options.rate_limit_rps}"
        f" --user-agent '{agent}'{storage}"
    )


def _run_partition_with_progress(
    options: RunOptions, partition_id: int, *, show_progress: bool = True
) -> dict:
    """Run one partition with progress, auto-merging on full success."""
    plan = load_plan(options)
    partition = next(
        (
            item
            for item in plan.get("partitions", [])
            if item["partition_id"] == partition_id
        ),
        None,
    )
    if partition is None:
        raise ValueError(f"partition {partition_id} is not present in plan.json")
    total = sum(
        chunk["end_row"] - chunk["start_row"] + 1
        for chunk in partition.get("chunks", [])
    )
    bar = tqdm(
        total=total,
        unit="cik",
        desc=f"partition {partition_id}",
        disable=not show_progress,
    )
    try:
        with logging_redirect_tqdm():
            return run_partition_with_automerge(
                options, partition_id, progress=make_tqdm_callback(bar)
            )
    finally:
        bar.close()


def _translate_merge_error(func):
    def wrapper(*call_args, **call_kwargs):
        try:
            return func(*call_args, **call_kwargs)
        except MergeError as exc:
            raise ValueError(str(exc)) from exc

    return wrapper


def _merge_partition_with_progress(
    options: RunOptions, partition_id: int, *, show_progress: bool = True
) -> dict:
    """Merge one partition with progress."""
    bar = tqdm(
        total=3,
        unit="stage",
        desc=f"merge partition {partition_id}",
        disable=not show_progress,
    )
    try:
        with logging_redirect_tqdm():
            return merge_one_partition(
                options,
                partition_id,
                progress=make_merge_progress_callback(bar),
            ).to_dict()
    finally:
        bar.close()


def _merge_final_with_progress(
    options: RunOptions, *, show_progress: bool = True
) -> dict:
    """Merge final artifacts with progress."""
    plan = load_plan(options)
    bar = tqdm(
        total=len(plan.get("partitions", [])) + 2,
        unit="step",
        desc="final merge",
        disable=not show_progress,
    )
    try:
        with logging_redirect_tqdm():
            return merge(
                options,
                progress=make_merge_progress_callback(bar),
            ).to_dict()
    finally:
        bar.close()


def interactive_wizard(args, project_config) -> int:
    """Adapt Phase 1 to the shared interactive menu."""
    base_options = options_from_args(args, project_config)
    try:
        base_options.validate()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    state = {
        "run_id": base_options.run_id,
        "artifacts_dir": base_options.artifacts_dir,
        "source_manifest": base_options.source_manifest,
        "base_metadata_manifest": base_options.base_metadata_manifest,
    }

    def _options() -> RunOptions:
        return replace(
            base_options,
            run_id=state["run_id"],
            artifacts_dir=state["artifacts_dir"],
            source_manifest=state["source_manifest"],
            base_metadata_manifest=state["base_metadata_manifest"],
            augmentation=bool(
                state["source_manifest"] and state["base_metadata_manifest"]
            ),
        )

    def _update_state_from_plan(plan: dict) -> None:
        run_options = plan.get("run_options") or {}
        if "artifacts_dir" in run_options:
            state["artifacts_dir"] = run_options["artifacts_dir"]
        if "run_id" in run_options:
            state["run_id"] = run_options["run_id"]
        elif plan.get("run_id"):
            state["run_id"] = plan["run_id"]
        if run_options.get("source_manifest"):
            state["source_manifest"] = run_options["source_manifest"]
        if run_options.get("base_metadata_manifest"):
            state["base_metadata_manifest"] = run_options["base_metadata_manifest"]

    def _root():
        options = _options()
        if options.base_metadata_manifest:
            return artifacts_root(options.base_metadata_manifest)
        direct = artifacts_root(options.artifacts_dir)
        if (direct / "manifests").is_dir():
            return direct
        parent = artifacts_root(Path(options.artifacts_dir).parent)
        return parent if (parent / "manifests").is_dir() else direct

    def _find_in_progress_runs(root: Path) -> list[dict]:
        from .core.paths import resolve_metadata_paths

        metadata_paths = resolve_metadata_paths(env={"ARTIFACTS_ROOT": str(root)})
        runs_dir = metadata_paths.phase_paths.runs_root
        if not runs_dir.is_dir():
            return []
        found = []
        for entry in sorted(runs_dir.iterdir()):
            if entry.is_dir():
                plan_file = entry / "plan.json"
                if plan_file.is_file():
                    try:
                        p = load_json(plan_file)
                        run_id = p.get("run_id", entry.name)
                        snap_manifest = metadata_paths.snapshot_manifest_path(run_id)
                        if not snap_manifest.is_file():
                            found.append(
                                {"run_dir": entry, "plan": p, "run_id": run_id}
                            )
                    except (OSError, ValueError):
                        continue
        return found

    def _pick(entries: list[dict], prompt: str) -> dict | None:
        if not entries:
            return None
        raw = input(prompt).strip()
        try:
            index = int(raw) if raw else 1
        except ValueError:
            index = 1
        index = min(max(index, 1), len(entries))
        return entries[index - 1]

    def _refresh_source_snapshot() -> tuple[str, dict]:
        options = _options()
        result = refresh_company_tickers(
            artifacts_root=artifacts_root(options.artifacts_dir),
            user_agent=options.user_agent,
            timeout_s=options.timeout_s,
            max_retries=options.max_retries,
            rate_limit_rps=options.rate_limit_rps,
            cache_dir=options.cache_dir or None,
        )
        manifest_path = artifacts_root(options.artifacts_dir) / result["manifest_path"]
        print(
            "  source snapshot published:"
            f" {result['snapshot_id'][:12]}"
            f" ({result['unique_cik_count']} CIKs,"
            f" {result['listing_row_count']} listings)"
        )
        return str(manifest_path), result

    def _prompt_augmentation_inputs() -> tuple[str, str] | None:
        root = _root()
        sources = discover_source_manifests(root)
        if not sources:
            answer = (
                input(
                    "  no source snapshot found; refresh the SEC listing source now? (Y/n) "
                )
                .strip()
                .lower()
            )
            if answer not in ("", "y", "yes"):
                return None
            _refresh_source_snapshot()
            sources = discover_source_manifests(root)
            if not sources:
                return None
        print("\nSource snapshots (latest first):")
        for index, item in enumerate(sources, start=1):
            print(
                f"  {index}. {item['snapshot_id'][:12]}"
                f" retrieved={item['retrieved_at']}"
                f" listings={item['listing_row_count']}"
                f" ciks={item['unique_cik_count']}"
            )
        source = _pick(sources, "Source snapshot [1]: ")
        if source is None:
            return None
        bases = discover_base_metadata_manifests(root)
        if not bases:
            print("  no base metadata snapshot / manifest found")
            return None
        pointer = get_current_snapshot_pointer(
            root, phase="metadata", dataset="submission_metadata"
        )
        current_id = pointer.get("snapshot_id") if pointer else None
        print("\nFinalized metadata snapshots / manifests:")
        for index, item in enumerate(bases, start=1):
            is_cur = " [current]" if item.get("run_id") == current_id else ""
            print(
                f"  {index}. {item['kind']}{is_cur} rows={item['row_count']}"
                f" run={item['run_id']}"
                f" sha={item['artifact_sha256'][:12]}"
            )
        base = _pick(bases, "Base metadata manifest [1]: ")
        if base is None:
            return None
        return source["manifest_path"], base["manifest_path"]

    def _ensure_augmentation_plan(options: RunOptions):
        plan_path = Path(options.artifacts_dir) / "plan.json"
        if plan_path.is_file():
            print(
                f"\nExisting plan in {options.artifacts_dir} will be replaced by"
                " this augmentation plan."
            )
            if input("Regenerate augmentation plan? (y/N) ").strip().lower() not in (
                "y",
                "yes",
            ):
                return None
        plan = build_plan(options)
        _update_state_from_plan(plan)
        print(
            f"Augmentation plan created: {plan['row_count']} delta CIKs (run: {state.get('run_id', 'default')}),"
            f" worklist {plan.get('worklist_path')}"
        )
        return plan

    def _adopt_existing_plan(options: RunOptions):
        """Adopt an existing augmentation plan identity without rewriting it."""
        if options.source_manifest or options.base_metadata_manifest:
            return None
        plan_path = Path(options.artifacts_dir) / "plan.json"
        if not plan_path.is_file():
            return None
        try:
            raw = json.loads(plan_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        run_options = raw.get("run_options") or {}
        source = run_options.get("source_manifest")
        base = run_options.get("base_metadata_manifest")
        if not raw.get("augmentation") or not source or not base:
            return None
        _update_state_from_plan(raw)
        try:
            plan = load_plan(_options())
        except (FileNotFoundError, ValueError):
            state["source_manifest"] = None
            state["base_metadata_manifest"] = None
            return None
        print(
            "\nAdopted existing augmentation plan identity:"
            f"\n  source-manifest: {source}"
            f"\n  base-metadata-manifest: {base}"
        )
        print(f"Loaded augmentation plan: {plan['row_count']} delta CIKs")
        return plan

    def ensure_plan(options: RunOptions) -> dict:
        root = _root()
        # Auto-resume in-progress run when launched without an explicit custom artifacts dir
        if base_options.artifacts_dir == DEFAULT_ARTIFACTS and not getattr(
            args, "artifacts", None
        ):
            in_progress = _find_in_progress_runs(root)
            if in_progress:
                active = in_progress[-1]
                _update_state_from_plan(active["plan"])
                state["artifacts_dir"] = str(active["run_dir"])
                state["run_id"] = active["run_id"]
                try:
                    plan = load_plan(_options())
                    print(
                        f"\nResumed active in-progress run: {active['run_id']}"
                        f" ({len(plan['chunks'])} chunks, {plan['row_count']} CIKs)"
                    )
                    return plan
                except (FileNotFoundError, ValueError):
                    pass

        try:
            plan = load_plan(_options())
            _update_state_from_plan(plan)
            print(
                f"\nLoaded existing plan: {len(plan['chunks'])} chunks,"
                f" {plan['row_count']} CIKs"
            )
            return plan
        except FileNotFoundError:
            pass
        except ValueError as exc:
            print(f"\nExisting plan rejected: {exc}")
            adopted = _adopt_existing_plan(_options())
            if adopted is not None:
                return adopted
            answer = (
                input(
                    f"Regenerate the plan in {state['artifacts_dir']}?"
                    " This replaces plan.json (y/N) "
                )
                .strip()
                .lower()
            )
            if answer in ("y", "yes"):
                plan = build_plan(_options())
                _update_state_from_plan(plan)
                print(
                    f"Plan created: {len(plan['chunks'])} chunks,"
                    f" {plan['row_count']} CIKs"
                )
                return plan

            raise SystemExit(
                "aborted: plan identity mismatch; rerun with the matching"
                " --augmentation/--source-manifest/--base-metadata-manifest flags"
            )

        pointer = get_current_snapshot_pointer(
            root, phase="metadata", dataset="submission_metadata"
        )
        if pointer is not None:
            cur_id = pointer.get("snapshot_id", "current")
            prompt_text = (
                f"Active snapshot: {cur_id}.\n"
                f"No active run in {state['artifacts_dir']}."
                " Create: [A]ugmentation plan (delta against current), [f]resh plan from CSV, [q]uit?"
                " (A/f/q) "
            )
            default_choice = "a"
        else:
            prompt_text = (
                f"No valid plan.json in {state['artifacts_dir']}."
                " Create: [F]resh plan from CSV, [a]ugmentation plan, [q]uit?"
                " (F/a/q) "
            )
            default_choice = "f"

        answer = input(prompt_text).strip().lower()
        if not answer:
            answer = default_choice

        if answer in ("a", "augmentation"):
            selected = _prompt_augmentation_inputs()
            if selected is None:
                raise SystemExit("aborted: augmentation inputs unavailable")
            state["source_manifest"], state["base_metadata_manifest"] = selected
            plan = build_plan(_options())
            _update_state_from_plan(plan)
            print(
                f"Augmentation plan created: {plan['row_count']} delta CIKs (run: {state.get('run_id', 'default')})"
            )
            return plan
        if answer in ("f", "fresh", "y", "yes"):
            plan = build_plan(_options())
            _update_state_from_plan(plan)
            print(
                f"Plan created: {len(plan['chunks'])} chunks, {plan['row_count']} CIKs (run: {state.get('run_id', 'default')})"
            )
            return plan
        raise SystemExit("aborted: run `plan` first or answer yes to create it")

    def _action_refresh_source():
        answer = (
            input("Fetch live SEC listing source (network request)? (y/N) ")
            .strip()
            .lower()
        )
        if answer not in ("y", "yes"):
            return "cancelled"
        _manifest_path, result = _refresh_source_snapshot()
        return {
            **result,
            "plan_unchanged": True,
            "message": "current plan unchanged; choose augmentation to use this source",
        }

    def _action_prepare_augmentation():
        selected = _prompt_augmentation_inputs()
        if selected is None:
            return "augmentation inputs unavailable"
        state["source_manifest"], state["base_metadata_manifest"] = selected
        plan = _ensure_augmentation_plan(_options())
        if plan is None:
            return "aborted; existing plan unchanged"
        _update_state_from_plan(plan)
        return {
            "mode": "augmentation",
            "run_id": state.get("run_id"),
            "delta_ciks": plan["row_count"],
            "effective_input_fingerprint": plan.get("effective_input_fingerprint"),
            "worklist": plan.get("worklist_path"),
            "base_metadata_manifest": state["base_metadata_manifest"],
            "source_manifest": state["source_manifest"],
        }

    def _action_manage_snapshots():
        root = _root()
        snaps = list_snapshots(
            phase="metadata", dataset="submission_metadata", artifacts_root=root
        )
        pointer = get_current_snapshot_pointer(
            root, phase="metadata", dataset="submission_metadata"
        )
        current_id = pointer.get("snapshot_id") if pointer else None
        if not snaps:
            print("\nNo published metadata snapshots found.")
            return "no_snapshots"
        print("\nMetadata Snapshots:")
        print(
            f"{'#':<3} {'Snapshot ID':<14} {'Status':<10} {'CIKs':>8} {'Parts':>6} {'Parent':<10}"
        )
        print("-" * 60)
        for idx, s in enumerate(snaps, start=1):
            is_cur = "[current]" if s["snapshot_id"] == current_id else ""
            parent = s.get("parent_snapshot_id") or "none"
            print(
                f"{idx:<3} {s['snapshot_id']:<14} {is_cur:<10} {s['effective_cik_count']:>8,d} {s['part_count']:>6d} {parent:<10}"
            )
        print("-" * 60)
        choice = input(
            "\nEnter # to switch active pointer (or Enter to keep current): "
        ).strip()
        if not choice:
            return "kept_current"
        try:
            sel_idx = int(choice) - 1
            selected = snaps[sel_idx]
            update_current_snapshot_pointer(
                selected["snapshot_id"],
                manifest_path=selected["manifest_path"],
                phase="metadata",
                dataset="submission_metadata",
                artifacts_root=root,
            )
            print(f"\nActive snapshot pointer updated to: {selected['snapshot_id']}")
            return {"active_snapshot": selected["snapshot_id"]}
        except (ValueError, IndexError):
            print("Invalid selection.")
            return "invalid_selection"

    return run_interactive(
        InteractivePhase(
            ensure_plan=lambda: ensure_plan(_options()),
            preview=lambda: preview_sample(_options()),
            status=lambda: get_status(_options()),
            run_partition=lambda partition_id: _run_partition_with_progress(
                _options(), partition_id, show_progress=not args.no_progress
            ),
            partition_command=lambda partition_id: partition_command(
                _options(), partition_id
            ),
            merge_partition=_translate_merge_error(
                lambda partition_id: _merge_partition_with_progress(
                    _options(), partition_id, show_progress=not args.no_progress
                )
            ),
            merge_final=_translate_merge_error(
                lambda: _merge_final_with_progress(
                    _options(), show_progress=not args.no_progress
                )
            ),
            extra_actions=(
                ExtraAction(
                    "s",
                    "Refresh source (does not alter current plan)",
                    _action_refresh_source,
                ),
                ExtraAction(
                    "a",
                    "Prepare augmentation (source + base + delta plan)",
                    _action_prepare_augmentation,
                ),
                ExtraAction(
                    "p",
                    "Inspect or switch active snapshot pointer",
                    _action_manage_snapshots,
                ),
            ),
        )
    )
