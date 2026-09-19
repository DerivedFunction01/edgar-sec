"""Interactive Phase 02 runner and launcher module."""

from __future__ import annotations

import builtins
import json
import logging
import shutil
import sys
from contextlib import suppress
from pathlib import Path

from tqdm import tqdm

from defs.runtime import resolve_paths, resolve_source
from defs.runtime.artifacts import get_current_snapshot_pointer
from defs.runtime.progress import make_merge_progress_callback
from defs.runtime.resources import derive_resources
from defs.storage import StorageError, load_json

from .cli import main as cli_main
from .core import config as phase_config
from .core import discovery
from .core.materialize import materialize
from .core.paths import resolve_filing_paths
from .core.target_plan import expand, plan

log = logging.getLogger("filing_extraction.run")


def _prompt(prompt: str, default: str = "") -> str:
    try:
        return builtins.input(prompt).strip() or default
    except EOFError:
        return default


def _default_source() -> tuple[str, str]:
    paths = resolve_paths()
    pointer = get_current_snapshot_pointer(
        paths.artifacts_root, phase="metadata", dataset="submission_metadata"
    )
    if pointer and "manifest_path" in pointer:
        snap = paths.artifacts_root / pointer["manifest_path"]
        if snap.is_file():
            return "manifest", str(snap)
    try:
        manifests, _ = resolve_source("submission_metadata", phase="metadata")
        m_path = paths.manifest_path_for(
            phase="metadata",
            dataset="submission_metadata",
            artifact_id_value=manifests[0]["artifact_id"],
            partition=manifests[0].get("partition", ""),
        )
        return "manifest", str(m_path)
    except (FileNotFoundError, OSError):
        pass
    pub = paths.published_dataset_path("metadata", "submission_metadata", "parquet")
    return ("artifact", str(pub)) if pub.is_file() else ("artifact", "")


def _get_context_summary() -> dict:
    paths = resolve_filing_paths()
    ctx: dict = {
        "p1_snapshot_id": None,
        "p1_ciks": 0,
        "p1_filings": 0,
        "p1_parts": 0,
        "catalog_snapshot_id": None,
        "catalog_forms": 0,
        "catalog_targets": 0,
    }
    p1 = get_current_snapshot_pointer(
        paths.artifacts_root, phase="metadata", dataset="submission_metadata"
    )
    if p1 and "manifest_path" in p1:
        sp = paths.artifacts_root / p1["manifest_path"]
        if sp.is_file():
            ctx["p1_snapshot_id"] = p1.get("snapshot_id", "current")
            with suppress(Exception):
                sm = load_json(sp)
                ctx["p1_ciks"] = sm.get("effective_cik_count", sm.get("row_count", 0))
                ctx["p1_filings"] = sm.get("filing_record_count", 0)
                ctx["p1_parts"] = len(sm.get("resolved_parts", []))

    p2 = get_current_snapshot_pointer(
        paths.artifacts_root, phase="filing_extraction", dataset="filing_catalog"
    )
    if p2 and "manifest_path" in p2:
        cp = paths.artifacts_root / p2["manifest_path"]
        if cp.is_file():
            ctx["catalog_snapshot_id"] = p2.get("snapshot_id", "current")
            with suppress(Exception):
                cm = load_json(cp)
                ctx["catalog_targets"] = cm.get("target_rows", 0)
                ctx["catalog_forms"] = cm.get("form_count", 0)

    if not ctx["catalog_snapshot_id"]:
        catalogs = discovery.discover_catalogs(str(paths.project.manifests_root))
        if catalogs:
            latest = catalogs[-1]
            ctx["catalog_snapshot_id"] = latest["catalog_id"]
            ctx["catalog_forms"] = latest.get("form_count", 0)
            ctx["catalog_targets"] = latest.get("target_rows", 0)
    return ctx


def _print_context_header() -> None:
    ctx = _get_context_summary()
    print("=" * 70)
    print("Phase 02: Filing Catalog (No-Network Materialize & Target Planner)")
    print("-" * 70)
    if ctx["p1_snapshot_id"]:
        print(
            f"Active Upstream:  Snapshot {ctx['p1_snapshot_id']} "
            f"({ctx['p1_ciks']:,} CIKs, {ctx['p1_filings']:,} filing records, {ctx['p1_parts']} parts)"
        )
    else:
        print("Active Upstream:  (no active Phase 01 snapshot detected)")
    if ctx["catalog_snapshot_id"]:
        print(
            f"Catalog Snapshot: Snapshot {ctx['catalog_snapshot_id']} "
            f"({ctx['catalog_targets']:,} filing targets across {ctx['catalog_forms']} forms)"
        )
    else:
        print("Catalog Snapshot: (no active catalog snapshot; choose 1 to materialize)")
    print("=" * 70)


def _select_catalog() -> str | None:
    catalogs = discovery.discover_catalogs(
        str(resolve_paths("filing_extraction").project.manifests_root)
    )
    if not catalogs:
        print("  no published catalog manifests found; run materialize first")
        return None
    if len(catalogs) == 1:
        cat = catalogs[0]
        print(
            f"  Catalog: {cat['catalog_id']} ({cat.get('target_rows', 0):,} targets, {cat.get('form_count', 0)} forms)"
        )
        return cat["catalog_id"]
    print("  Multiple catalogs found; choose one:")
    for i, cat in enumerate(catalogs, start=1):
        print(
            f"    {i}. {cat['catalog_id']} ({cat.get('target_rows', 0):,} targets, {cat.get('form_count', 0)} forms)"
        )
    choice = _prompt(f"Select catalog [1-{len(catalogs)}] [1]: ", "1")
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(catalogs):
            return catalogs[idx]["catalog_id"]
    except ValueError:
        pass
    return catalogs[0]["catalog_id"]


class _StageBar:
    def __init__(self, desc: str) -> None:
        self._bar = tqdm(total=None, unit="stage", desc=desc)
        self._adapter = make_merge_progress_callback(self._bar)

    def __call__(self, event: dict) -> None:
        etype = event.get("type")
        if etype == "batch_done":
            batch, total = event.get("batch", 1), event.get("total_batches")
            done, total_ciks = event.get("ciks_done"), event.get("total_ciks")
            blbl = f"{batch}/{total}" if total else str(batch)
            self._bar.set_description(f"materialize (batch {blbl})")
            pfix = {
                "batch": blbl,
                "cik": f"{event.get('cik_start', '')}..{event.get('cik_end', '')}",
            }
            if done is not None and total_ciks:
                pfix["done"] = (
                    f"{done:,}/{total_ciks:,} ({done * 100 / total_ciks:.1f}%)"
                )
            self._bar.set_postfix(pfix)
            return
        if etype == "merge_stage":
            stage, total_units = event.get("stage", ""), event.get("total_units")
            if total_units is not None:
                self._bar.total = int(total_units)
                self._bar.refresh()
            if stage.startswith("targets:"):
                self._bar.set_description(f"targets ({stage.split(':', 1)[1]})")
            elif stage in (
                "company_profiles",
                "publish_manifest",
            ):
                self._bar.set_description(stage.replace("_", " "))
            elif stage == "discover_forms":
                self._bar.set_description(f"forms ({event.get('forms', 0)} discovered)")
        self._adapter(event)

    def close(self) -> None:
        self._bar.close()


def _menu_materialize() -> None:
    source_kind, source_default = _default_source()
    res = derive_resources()
    kwargs: dict = {
        "source_batch_size": phase_config.load().source_batch_size,
        "threads": res.threads,
        "memory_limit": res.memory_limit,
        "temp_directory": res.temp_directory,
    }
    p_msg = (
        f"Source artifact or manifest [{source_default}]: "
        if source_default
        else "Source artifact or manifest path: "
    )
    source = _prompt(p_msg, source_default)
    if not source:
        print("  source is required")
        return
    if source_kind == "manifest" or source.endswith(".json"):
        kwargs["source_manifest"] = source
    else:
        kwargs["source_artifact"] = source

    # No output_root: the engine stages transiently and publishes the durable
    # manifest-tree snapshot, advancing the filing_catalog current pointer.
    print(f"  Output: {resolve_filing_paths().catalog_snapshots_dir}")
    print(f"  Batch size: {kwargs['source_batch_size']} rows")
    print(
        f"  DuckDB: {res.threads} threads, {res.memory_limit}, spill={res.temp_directory}"
    )

    bar = _StageBar("materialize")
    kwargs["progress"] = bar
    try:
        result = materialize(**kwargs)
    except KeyboardInterrupt:
        print("\n  interrupted; no catalog manifest was published")
        return
    except (ValueError, FileNotFoundError, StorageError) as exc:
        print(f"  error: {exc}")
        return
    finally:
        bar.close()
    print(json.dumps(result, indent=2, sort_keys=True))


def _auto_generate_policy(catalog_id: str, dest: Path | None = None) -> Path:
    from .core.selection_policy import auto_generate_policy

    if dest is None:
        dest = resolve_paths("filing_extraction").phase_root / "selection_policy.json"
    auto_generate_policy(catalog_id, dest=dest)
    return dest


def _select_policy(catalog: str) -> str | None:
    """Interactively choose a valid selection policy JSON for policy scope."""
    policies: list[dict] = []
    with suppress(ImportError, OSError, ValueError):
        policies = discovery.discover_policies()
    if not policies:
        default_path = (
            resolve_paths("filing_extraction").phase_root / "selection_policy.json"
        )
        answer = _prompt(
            f"  No valid selection policy JSON found. "
            f"Generate template at {default_path}? [Y/n]: ",
            "Y",
        )
        if answer.strip().lower() in ("", "y", "yes"):
            try:
                _auto_generate_policy(catalog, default_path)
            except (ValueError, OSError) as exc:
                print(f"  could not generate a policy template: {exc}")
                return None
            print(
                f"\n  Created default selection policy template at:\n"
                f"    {default_path}\n"
                f"  Edit it, then rerun 'Plan filing targets' to select it."
            )
        return None
    if len(policies) == 1:
        p = policies[0]
        chosen = _prompt(
            f"  Selection policy: {p['name']} (corpus {p['corpus_id']}, "
            f"{len(p['forms'])} forms, {p['base_content_units']} units) "
            f"[{p['path']}]: ",
            p["path"],
        )
        if not Path(chosen).is_file():
            print(f"  selection policy file not found: {chosen}")
            return None
        return chosen
    print("  Valid selection policies found:")
    for idx, p in enumerate(policies, start=1):
        print(
            f"    {idx}. {p['name']} (corpus {p['corpus_id']}, "
            f"{len(p['forms'])} forms, {p['base_content_units']} units, "
            f"level {p['level']})"
        )
    choice = _prompt(f"  Select policy [1-{len(policies)}] or enter a path: ", "1")
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(policies):
            return policies[idx]["path"]
    except ValueError:
        pass
    if not Path(choice).is_file():
        print(f"  selection policy file not found: {choice}")
        return None
    return choice


def _menu_plan() -> None:
    catalog = _select_catalog()
    if not catalog:
        return
    scope_choice = _prompt(
        "Selection scope [1. Deterministic plan, 2. Policy-driven selection] [1]: ",
        "1",
    )
    scope = "policy" if scope_choice in ("2", "policy") else "deterministic"
    out_root = str(resolve_paths("filing_extraction").runs_root)

    if scope == "policy":
        pol_path = _select_policy(catalog)
        if not pol_path:
            return
        bar = _StageBar("plan targets")
        try:
            result = plan(
                catalog,
                out_root,
                scope="policy",
                selection_policy_path=pol_path,
                progress=bar,
            )
        except KeyboardInterrupt:
            print("\n  interrupted; no target plan was published")
            return
        except (ValueError, FileNotFoundError, StorageError) as exc:
            print(f"  error: {exc}")
            return
        finally:
            bar.close()
        print(json.dumps(result, indent=2, sort_keys=True))
        return

    settings = phase_config.load()
    default_forms, default_amendment = settings.target_forms, settings.amendment
    forms_default = ", ".join(default_forms) if default_forms else ""
    forms_raw = _prompt(f"Forms filter [{forms_default}]: ", forms_default)
    forms = (
        tuple(f.strip() for f in forms_raw.split(",") if f.strip())
        if forms_raw
        else default_forms
    )
    amendment = _prompt(f"Amendment policy [{default_amendment}]: ", default_amendment)
    bar = _StageBar("plan targets")
    try:
        result = plan(
            catalog,
            out_root,
            scope="deterministic",
            forms=forms,
            amendment=amendment,
            limit=None,
            progress=bar,
        )
    except KeyboardInterrupt:
        print("\n  interrupted; no target plan was published")
        return
    except (ValueError, FileNotFoundError, StorageError) as exc:
        print(f"  error: {exc}")
        return
    finally:
        bar.close()
    print(json.dumps(result, indent=2, sort_keys=True))


def _menu_status() -> None:
    st = discovery.status()
    print("\n" + "=" * 70)
    print("Phase 02 Status Summary")
    print("=" * 70)
    cats = st.get("catalogs", [])
    print(f"Catalogs ({len(cats)} found):")
    for c in cats:
        print(
            f"  - {c['catalog_id']}: {c.get('target_rows', 0):,} targets across {c.get('form_count', 0)} forms"
        )
    plans = st.get("plans", [])
    print(f"\nTarget Plans ({len(plans)} found):")
    for p in plans:
        locs = p.get("unique_locators_count") or p.get("active_targets_count") or "?"
        print(
            f"  - {p['plan_id']} ({locs} locators) [catalog: {p.get('catalog_id', '?')}]"
        )
    print("=" * 70 + "\n")


def _select_parent_plan() -> str | None:
    plans = []
    with suppress(ImportError, OSError, ValueError):
        plans = discovery.discover_plans()
    if not plans:
        return _prompt("Parent plan directory: ") or None
    if len(plans) == 1:
        p = plans[0]
        locs = p.get("unique_locators_count") or p.get("active_targets_count") or "?"
        print(f"  Parent plan: {p['plan_id']} ({locs} locators) -> {p['path']}")
        return _prompt(f"  Plan directory [{p['path']}]: ", p["path"])
    print("  Discovered target plans:")
    for idx, p in enumerate(plans, start=1):
        locs = p.get("unique_locators_count") or p.get("active_targets_count") or "?"
        print(f"    {idx}. {p['plan_id']} ({locs} locators)")
    choice = _prompt(f"  Select plan [1-{len(plans)}] [1]: ", "1")
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(plans):
            return plans[idx]["path"]
    except ValueError:
        pass
    return plans[0]["path"]


def _menu_expand() -> None:
    parent_plan = _select_parent_plan()
    if not parent_plan:
        return
    raw_units = _prompt("Target units (total unique locators): ")
    if not raw_units:
        print("  target units is required")
        return
    try:
        target_units = int(raw_units)
    except ValueError:
        print("  target units must be an integer")
        return
    bar = _StageBar("expand target plan")
    try:
        result = expand(parent_plan, target_units, progress=bar)
    except KeyboardInterrupt:
        print("\n  interrupted; no child plan was published")
        return
    except (ValueError, FileNotFoundError, StorageError) as exc:
        print(f"  error: {exc}")
        return
    finally:
        bar.close()
    print(json.dumps(result, indent=2, sort_keys=True))


def _menu_prune() -> None:
    fp = resolve_filing_paths()
    print("\n" + "=" * 70)
    print("Pruning Scratch & Non-Snapshot Directories")
    print("-" * 70)
    pruned_count = 0
    transient_dir = fp.transient_root
    if transient_dir.exists():
        for item in transient_dir.iterdir():
            shutil.rmtree(item, ignore_errors=True)
            pruned_count += 1
            print(f"  Removed transient directory: {item.name}")

    meta_sub = fp.meta_submission_metadata_dir
    if meta_sub.exists():
        for sub_dir in meta_sub.iterdir():
            if sub_dir.is_dir() and sub_dir.name != "snapshots":
                shutil.rmtree(sub_dir, ignore_errors=True)
                pruned_count += 1
                print(f"  Removed obsolete directory: {sub_dir.name}")

    fe_root = fp.manifests_filing_extraction_dir
    if fe_root.exists():
        for sub_dir in fe_root.iterdir():
            if sub_dir.is_dir() and sub_dir.name not in (
                "filing_catalog",
                "target_plans",
            ):
                shutil.rmtree(sub_dir, ignore_errors=True)
                pruned_count += 1
                print(f"  Removed obsolete catalog directory: {sub_dir.name}")

    print(f"Pruning complete. {pruned_count} directories cleaned.")
    print("=" * 70 + "\n")


def interactive_menu() -> int:
    while True:
        print()
        _print_context_header()
        print("  1. Materialize catalog")
        print("  2. Plan filing targets")
        print("  3. Expand plan (child plan with additional locators)")
        print("  4. Show status")
        print("  5. Prune transient & scratch files")
        print("  0. Exit")
        choice = _prompt("\nChoice [0]: ", "0")
        if choice == "0":
            return 0
        if choice == "1":
            _menu_materialize()
        elif choice == "2":
            _menu_plan()
        elif choice == "3":
            _menu_expand()
        elif choice == "4":
            _menu_status()
        elif choice == "5":
            _menu_prune()
        else:
            print("  unknown choice")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help"):
        print(
            "usage: python run.py filing-catalog            interactive menu\n"
            "       python run.py filing-catalog materialize --source-manifest <m>\n"
            "       python run.py filing-catalog plan --catalog <dir>\n"
            "       python run.py filing-catalog expand --parent-plan <dir> --target-units <n>\n"
            "       python run.py filing-catalog status"
        )
        return 0
    if not argv:
        try:
            return interactive_menu()
        except KeyboardInterrupt:
            print("\ninterrupted")
            return 130
    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
