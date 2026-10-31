"""Tests for distribution CLI commands and subparser dispatch."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.distribution.cli import (
    attach_distrib_subparser,
    cmd_commands,
    cmd_export,
    cmd_import,
    cmd_list,
    cmd_worker,
)
from edgar_sec.infra.distribution.guards import read_bundle_manifest
from edgar_sec.infra.distribution.protocol import (
    DistributionWork,
    ImportReport,
    WorkerAssignment,
    WorkerReceipt,
)
from edgar_sec.infra.distribution.receipt import build_worker_receipt, read_receipt


class DummyAdapter:
    pipeline_name = "mock_pipe"
    work_digest = "a" * 64

    def list_work_items(self, artifacts_root: Path | None = None):
        return (DistributionWork("work-1", "Mock work", self.work_digest, 4),)

    def resolve_work(self, work_id: str, artifacts_root: Path | None = None) -> Any:
        if work_id != "work-1":
            raise ValueError("unknown work")
        return {"work_id": work_id, "chunk_count": 4}

    def describe_work(self, work_id: str, work: Any) -> DistributionWork:
        return DistributionWork(work_id, "Mock work", self.work_digest, 4)

    def default_destination(self, work_id: str) -> Path:
        return Path("dist") / work_id

    def export_worker_bundle(
        self, work: Any, assignment: WorkerAssignment, bundle_dir: Path
    ) -> None:
        (bundle_dir / "work.meta").write_text("ok", encoding="utf-8")

    def execute_worker(
        self,
        bundle_dir: Path,
        worker_id: str | None,
        *,
        workers: int | None = None,
    ) -> WorkerReceipt:
        manifest = read_bundle_manifest(bundle_dir)
        files = []
        for chunk_id in manifest["chunk_ids"]:
            chunk = bundle_dir / f"chunk-{chunk_id}.bin"
            chunk.write_bytes(b"chunk-data")
            files.append(chunk)
        return build_worker_receipt(
            pipeline=self.pipeline_name,
            work_id=manifest["work_id"],
            work_digest=manifest["work_digest"],
            assignment_id=manifest["assignment_id"],
            worker_id=worker_id or manifest["worker_id"],
            completed_chunks=manifest["chunk_ids"],
            output_files=files,
            bundle_root=bundle_dir,
            result_metadata={"record_count": 50},
        )

    def adopt_worker_bundle(
        self, work: Any, bundle_dir: Path, receipt: WorkerReceipt
    ) -> ImportReport:
        return ImportReport(
            "mock_pipe", "work-1", receipt.worker_id, receipt.completed_chunks, ()
        )


class FutureAcquisitionAdapter(DummyAdapter):
    pipeline_name = "acquisition"

    def execute_worker(
        self,
        bundle_dir: Path,
        worker_id: str | None,
        *,
        workers: int | None = None,
    ) -> WorkerReceipt:
        manifest = read_bundle_manifest(bundle_dir)
        body = bundle_dir / "body.txt"
        body.write_bytes(b"verified filing body")
        digest = file_sha256(body)
        return build_worker_receipt(
            pipeline=self.pipeline_name,
            work_id=manifest["work_id"],
            work_digest=manifest["work_digest"],
            assignment_id=manifest["assignment_id"],
            worker_id=worker_id or manifest["worker_id"],
            completed_chunks=manifest["chunk_ids"],
            output_files=[body],
            bundle_root=bundle_dir,
            result_metadata={
                "target_outcomes": [{"target_id": "target-1", "status": "selected"}],
                "body_sha256": digest,
            },
        )

    def adopt_worker_bundle(
        self, work: Any, bundle_dir: Path, receipt: WorkerReceipt
    ) -> ImportReport:
        assert receipt.result_metadata["target_outcomes"][0]["status"] == "selected"
        assert (
            receipt.file_records["body.txt"].sha256
            == receipt.result_metadata["body_sha256"]
        )
        return ImportReport(
            self.pipeline_name,
            "work-1",
            receipt.worker_id,
            receipt.completed_chunks,
            (),
        )


def test_cli_lifecycle(tmp_path: Path) -> None:
    adapter = DummyAdapter()
    destination = tmp_path / "dist"

    assert cmd_export(adapter, "work-1", worker_count=2, destination=destination) == 0
    worker_bundle = destination / "worker-00"
    assert (worker_bundle / "bundle.json").is_file()
    assert cmd_worker(adapter, worker_bundle) == 0
    assert (worker_bundle / "receipt.json").is_file()
    assert cmd_import(adapter, "work-1", worker_bundle) == 0
    assert cmd_list(adapter, destination=destination) == 0
    assert cmd_commands(adapter, "work-1", destination=destination) == 0


def test_attach_distrib_subparser() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="cmd", required=True)
    adapter = DummyAdapter()
    attach_distrib_subparser(subparsers, lambda _args: adapter)

    parsed = parser.parse_args(
        ["distrib", "export", "--work-id", "work-1", "--workers", "2"]
    )
    assert parsed.cmd == "distrib"
    assert parsed.distrib_command == "export"
    assert parsed.work_id == "work-1"


def test_pipeline_specific_run_claims_fit_generic_contract(tmp_path: Path) -> None:
    adapter = FutureAcquisitionAdapter()
    destination = tmp_path / "acquisition"
    assert cmd_export(adapter, "work-1", worker_count=1, destination=destination) == 0
    bundle = destination / "worker-00"
    assert cmd_worker(adapter, bundle) == 0
    receipt = read_receipt(bundle / "receipt.json")
    assert receipt.work_id == "work-1"
    assert receipt.file_records["body.txt"].size_bytes == len(b"verified filing body")
    assert cmd_import(adapter, "work-1", bundle) == 0
