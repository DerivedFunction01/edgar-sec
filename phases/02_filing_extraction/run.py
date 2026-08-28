"""Interactive Phase 02 runner and launcher module.

Selecting ``Phase 02: Filing Catalog`` from ``python run.py`` opens a
phase-specific menu. Explicit subcommands (``materialize``, ``plan``,
``status``) are forwarded verbatim to the canonical CLI so automation keeps one
contract with the command surface.

Phase 02 is a no-network workflow: it materializes a filing catalog from a
finalized Phase 01 artifact and plans deterministic target selections. It never
fetches, stores, or parses raw SEC filing documents; that is the separate
Phase 2.5 acquisition boundary described in the phase and roadmap docs.
"""

from __future__ import annotations

import builtins
import json
import logging
import sys
from pathlib import Path

from tqdm import tqdm

from defs.runtime import resolve_paths, resolve_source
from defs.runtime.progress import make_merge_progress_callback
from defs.runtime.resources import derive_resources
from defs.storage import StorageError

from .cli import main as cli_main
from .core import config as phase_config
from .core import discovery
from .core.materialize import materialize
from .core.target_plan import plan

log = logging.getLogger("filing_extraction.run")


def _prompt(prompt: str, default: str) -> str:
    try:
        raw = builtins.input(prompt).strip()
        return raw or default
    except EOFError:
        return default


def _read(prompt: str, default: str = "") -> str:
    """Read a value, returning its displayed default on blank input or EOF."""
    try:
        return builtins.input(prompt).strip() or default
    except EOFError:
        return default


def _phase_root() -> Path:
    return resolve_paths("filing_extraction").phase_root


def _default_source() -> tuple[str, str]:
    """Return a safe default source kind/path for the common local workspace."""
    paths = resolve_paths()
    try:
        manifests, _ = resolve_source("submission_metadata", phase="metadata")
        manifest_path = paths.manifest_path_for(
            phase="metadata",
            dataset="submission_metadata",
            artifact_id_value=manifests[0]["artifact_id"],
            partition=manifests[0].get("partition", ""),
        )
        return "manifest", str(manifest_path)
    except (FileNotFoundError, OSError):
        pass
    published = paths.published_dataset_path(
        "metadata", "submission_metadata", "parquet"
    )
    if published.is_file():
        return "artifact", str(published)
    return "artifact", ""


def _default_catalog() -> str:
    catalogs = discovery.discover_catalogs(str(_phase_root() / "catalogs"))
    if len(catalogs) == 1:
        return catalogs[0]["path"]
    if len(catalogs) > 1:
        print("  Multiple catalogs found; choose one:")
        for index, catalog in enumerate(catalogs, start=1):
            print(f"    {index}. {catalog['catalog_id']} ({catalog['path']})")
    return ""


def _default_catalog_root() -> str:
    return str(_phase_root() / "catalogs")


def _default_runs_root() -> str:
    return str(_phase_root() / "runs")


def _prompt_int(prompt: str) -> int | None:
    raw = _read(prompt)
    if raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        print(f"  invalid integer: {raw!r}")
        return None


class _StageBar:
    """tqdm stage bar driven by merge-style and batched progress events.

    Stage totals are announced when forms are discovered, while batch updates
    report live progress during the longest unnest streaming phase.
    """

    def __init__(self, desc: str) -> None:
        self._bar = tqdm(total=None, unit="stage", desc=desc)
        self._adapter = make_merge_progress_callback(self._bar)

    def __call__(self, event: dict) -> None:
        event_type = event.get("type")
        if event_type == "batch_done":
            batch = event.get("batch", 1)
            total_batches = event.get("total_batches")
            cik_start = event.get("cik_start", "")
            cik_end = event.get("cik_end", "")
            ciks_done = event.get("ciks_done")
            total_ciks = event.get("total_ciks")

            batch_label = f"{batch}/{total_batches}" if total_batches else str(batch)
            self._bar.set_description(f"materialize (batch {batch_label})")
            postfix = {
                "batch": batch_label,
                "cik": f"{cik_start}..{cik_end}",
            }
            if ciks_done is not None and total_ciks:
                postfix["done"] = (
                    f"{ciks_done:,}/{total_ciks:,} ({ciks_done * 100 / total_ciks:.1f}%)"
                )
            self._bar.set_postfix(postfix)
            return

        if event_type == "merge_stage":
            stage = event.get("stage", "")
            total_units = event.get("total_units")
            if total_units is not None:
                self._bar.total = int(total_units)
                self._bar.refresh()
            if stage.startswith("targets:"):
                form_name = stage.split(":", 1)[1]
                self._bar.set_description(f"targets ({form_name})")
            elif stage == "company_profiles":
                self._bar.set_description("company profiles")
            elif stage == "discover_forms":
                self._bar.set_description(f"forms ({event.get('forms', 0)} discovered)")
            elif stage == "occurrence_sources":
                self._bar.set_description("occurrence sources")
            elif stage == "publish_manifest":
                self._bar.set_description("publishing catalog")

        self._adapter(event)

    def close(self) -> None:
        self._bar.close()


def _menu_materialize() -> None:
    source_kind, source_default = _default_source()
    source_label = source_default or "required"
    source = _read(
        f"Source artifact path or manifest path [{source_label}]: ", source_default
    )
    if not source:
        print("  source is required")
        return
    output_root = _read(
        f"Output root [{_default_catalog_root()}]: ", _default_catalog_root()
    )
    settings = phase_config.load()
    resources = derive_resources()
    batch_raw = _read(
        f"Source rows per batch [{settings.source_batch_size}]: ",
        str(settings.source_batch_size),
    )
    try:
        source_batch_size = int(batch_raw)
    except ValueError:
        print(f"  invalid integer: {batch_raw!r}")
        return
    print(
        f"  DuckDB resources: {resources.threads} threads, "
        f"{resources.memory_limit}, spill={resources.temp_directory}"
    )
    bar = _StageBar("materialize")
    kwargs: dict = {
        "output_root": output_root,
        "progress": bar,
        "source_batch_size": source_batch_size,
        "threads": resources.threads,
        "memory_limit": resources.memory_limit,
        "temp_directory": resources.temp_directory,
    }
    if source_kind == "manifest" or source.endswith(".json"):
        kwargs["source_manifest"] = source
    else:
        kwargs["source_artifact"] = source
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


def _menu_plan() -> None:
    catalog_default = _default_catalog()
    catalog = _read(
        f"Catalog directory [{catalog_default or 'required'}]: ", catalog_default
    )
    if not catalog:
        print("  catalog directory is required")
        return
    forms_raw = _read("Forms (comma-separated, empty for all): ")
    forms = tuple(form.strip() for form in forms_raw.split(",") if form.strip())
    amendment = _prompt("Amendment [both]: ", "both")
    if amendment not in ("both", "original", "amendments"):
        print("  amendment must be both, original, or amendments")
        return
    limit = _prompt_int("Limit (empty for none): ")
    output_root = _read(f"Output root [{_default_runs_root()}]: ", _default_runs_root())
    bar = _StageBar("plan targets")
    try:
        result = plan(
            catalog,
            output_root,
            forms=forms,
            amendment=amendment,
            limit=limit,
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
    print(json.dumps(discovery.status(), indent=2, sort_keys=True))


def interactive_menu() -> int:
    while True:
        print("\nPhase 02: Filing Catalog (no-network materialize and plan)")
        print("  1. Materialize catalog")
        print("  2. Plan filing targets")
        print("  3. Show status")
        print("  0. Exit")
        choice = _prompt("\nChoice [0]: ", "0")
        if choice == "0":
            return 0
        if choice == "1":
            _menu_materialize()
        elif choice == "2":
            _menu_plan()
        elif choice == "3":
            _menu_status()
        else:
            print("  unknown choice")


def _usage() -> str:
    return (
        "usage: python run.py filing-catalog            interactive menu\n"
        "       python run.py filing-catalog materialize --source-manifest <m>\n"
        "       python run.py filing-catalog plan --catalog <dir>\n"
        "       python run.py filing-catalog status"
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help"):
        print(_usage())
        return 0
    if not argv:
        try:
            return interactive_menu()
        except KeyboardInterrupt:
            print("\ninterrupted")
            return 130
    # Forward explicit subcommands to the canonical CLI surface.
    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
