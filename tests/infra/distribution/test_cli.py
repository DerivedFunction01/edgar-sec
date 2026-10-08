"""Tests for distribution CLI commands and subparser dispatch."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from edgar_sec.infra.distribution.cli import (
    attach_distrib_subparser,
    cmd_commands,
    cmd_export,
    cmd_import,
    cmd_list,
    cmd_worker,
)
from edgar_sec.infra.distribution.protocol import (
    DistributionAdapter,
    ImportReport,
    WorkerAssignment,
    WorkerReceipt,
)
from edgar_sec.infra.distribution.receipt import build_worker_receipt


class DummyAdapter:
    """Mock distribution adapter for CLI testing."""

    pipeline_name = "mock_pipe"

    def resolve_plan(self, plan_id: str, artifacts_root: Path | None) -> Any:
        return {"plan_id": plan_id, "chunk_count": 4}

    def get_chunk_count(self, plan: Any) -> int:
        return int(plan["chunk_count"])

    def default_destination(self, plan_id: str) -> Path:
        from edgar_sec.foundation.runtime.settings.paths import (
            DEFAULT_DISTRIBUTION_ROOT,
        )

        return DEFAULT_DISTRIBUTION_ROOT / "mock_pipe" / plan_id

    def export_worker_bundle(
        self, plan: Any, assignment: WorkerAssignment, bundle_dir: Path
    ) -> None:
        (bundle_dir / "plan.meta").write_text("ok", encoding="utf-8")

    def execute_worker(
        self, bundle_dir: Path, worker_id: str | None, *, workers: int | None = None
    ) -> WorkerReceipt:
        chunk = bundle_dir / "chunk-0.bin"
        chunk.write_bytes(b"chunk-data")
        return build_worker_receipt(
            "mock_pipe", "p1", worker_id or "w1", (0,), 50, [chunk], bundle_dir
        )

    def adopt_worker_bundle(
        self, plan: Any, bundle_dir: Path, receipt: WorkerReceipt
    ) -> ImportReport:
        return ImportReport("mock_pipe", "p1", receipt.worker_id, (0,), ())


def test_cli_lifecycle(tmp_path: Path) -> None:
    """Verifies export, worker execution, and adoption cycle via CLI commands."""
    adapter = DummyAdapter()
    dest = tmp_path / "dist"

    assert cmd_export(adapter, "p1", worker_count=2, destination=dest) == 0
    w0_bundle = dest / "worker-00"
    assert (w0_bundle / "bundle.json").is_file()

    assert cmd_worker(adapter, w0_bundle) == 0
    assert (w0_bundle / "receipt.json").is_file()

    assert cmd_import(adapter, "p1", w0_bundle) == 0
    assert cmd_list(adapter, destination=dest) == 0
    assert cmd_commands(adapter, "p1", destination=dest) == 0


def test_attach_distrib_subparser() -> None:
    """Verifies subparser attachment and command line routing."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="cmd", required=True)
    adapter = DummyAdapter()
    attach_distrib_subparser(subparsers, lambda _args: adapter)

    parsed = parser.parse_args(
        ["distrib", "export", "--plan-id", "p1", "--workers", "2"]
    )
    assert parsed.cmd == "distrib"
    assert parsed.distrib_command == "export"
