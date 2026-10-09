from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from edgar_sec.pipelines.document_inventory.commands import run as run_command
from edgar_sec.pipelines.document_inventory.paths import inventory_run_paths


@dataclass
class _Summary:
    run_id: str
    cancelled: bool
    chunk_count: int = 0
    refusal_count: int = 0

    @property
    def status(self) -> str:
        return "cancelled" if self.cancelled else "completed"


def test_cancelled_run_marker_is_persisted_and_cleared(tmp_path, monkeypatch) -> None:
    paths = inventory_run_paths(tmp_path, "run-1")
    projection = SimpleNamespace(paths=paths)
    run = SimpleNamespace(
        parent_snapshot_id="",
        canonical_cohort_id="cohort",
        source_identity="plan:p",
        parser_version="parser",
        chunk_size=1,
        refresh_mode="normal",
        fetch_mode="live",
        fixture_id=None,
        work_order_version="1",
    )
    monkeypatch.setattr(run_command, "load_run_state", lambda *_args: (projection, run))
    summaries = iter((_Summary("run-1", True), _Summary("run-1", False)))
    monkeypatch.setattr(
        run_command, "run_missing_accessions", lambda *_args, **_kwargs: next(summaries)
    )
    args = SimpleNamespace(
        artifacts_root=str(tmp_path),
        run_id="run-1",
        workers=1,
        retry_failures=False,
        confirm_stale_lock=False,
        json=True,
    )

    assert run_command.cmd_run(args) == 130
    assert paths.cancelled_path().is_file()
    assert run_command.cmd_run(args) == 0
    assert not paths.cancelled_path().exists()
