"""Standalone interactive operator entrypoint for the snapshot DAG engine.

Autodiscovers snapshot repositories across workspace artifacts and runs the console.
"""

from __future__ import annotations

from pathlib import Path
import sys

from edgar_sec.foundation.runtime.paths import resolve_paths
from edgar_sec.infra.storage.dag.paths import DAGPaths
from .menu import DAGMenuConfig, run_dag_menu


def discover_snapshot_repositories() -> list[tuple[str, Path]]:
    """Scan standard project artifact locations for snapshot directories."""
    candidates: list[tuple[str, Path]] = []
    cwd = Path.cwd()
    artifacts_dir = resolve_paths().artifacts_root

    if DAGPaths(cwd).current_pointer.is_file():
        candidates.append(("Current working directory", cwd))

    for base in [cwd, artifacts_dir]:
        if not base.is_dir():
            continue
        for sub in base.rglob("snapshots"):
            if sub.is_dir() and (
                (sub / "current").is_dir() or (sub / "branches").is_dir()
            ):
                rel = sub.relative_to(cwd) if sub.is_relative_to(cwd) else sub
                candidates.append((str(rel), sub))

    unique: dict[Path, str] = {}
    for name, p in candidates:
        if p.resolve() not in unique:
            unique[p.resolve()] = name
    return [(v, k) for k, v in unique.items()]


def main(argv: list[str] | None = None) -> int:
    """Entry point for standalone interactive DAG operator."""
    repos = discover_snapshot_repositories()
    if not repos:
        target = resolve_paths().artifacts_root / "metadata" / "snapshots"
        config = DAGMenuConfig(snapshots_root=target, title="Snapshot DAG Console")
        return run_dag_menu(config, argv)

    if len(repos) == 1:
        name, path = repos[0]
        config = DAGMenuConfig(snapshots_root=path, title=f"Snapshot DAG: {name}")
        return run_dag_menu(config, argv)

    print("\nDiscovered Snapshot Repositories:")
    for idx, (name, _p) in enumerate(repos, start=1):
        print(f"  [{idx}] {name}")
    from edgar_sec.foundation.runtime.interactive import prompt_text

    choice = prompt_text("Select repository to manage [1]", "1").strip() or "1"
    try:
        idx = int(choice) - 1
        name, path = repos[idx]
    except (ValueError, IndexError):
        name, path = repos[0]

    config = DAGMenuConfig(snapshots_root=path, title=f"Snapshot DAG: {name}")
    return run_dag_menu(config, argv)


if __name__ == "__main__":
    sys.exit(main())
