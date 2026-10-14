"""High-level Edgar facade providing ergonomic querying, fetching, and inspection."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from edgar_sec.apps.client.models import FilingsResult
from edgar_sec.apps.runner.config import RunnerOptions, TargetSpec
from edgar_sec.apps.runner.coordinator import PipelineRunner
from edgar_sec.infra.sec_http.client import SecHttpClient


class Edgar:
    """Convenience client for querying, acquiring, and analyzing SEC filings."""

    def __init__(
        self,
        *,
        artifacts_root: Path | str | None = None,
        sec_client: SecHttpClient | None = None,
        workers: int | None = None,
    ) -> None:
        self.artifacts_root = (
            Path(artifacts_root) if artifacts_root is not None else None
        )
        self.sec_client = sec_client
        self.workers = workers

    def fetch(
        self,
        *,
        forms: Sequence[str] | str = (),
        ciks: Sequence[str | int] | str | int = (),
        dates: str | None = None,
        suffixes: Sequence[str] | str = (),
        role: str = "primary",
        limit: int | None = None,
        operation: str = "raw",
        family_operations: dict[str, str] | None = None,
    ) -> FilingsResult:
        """Execute end-to-end acquisition and return a relational FilingsResult."""
        form_tuple = (
            (forms,) if isinstance(forms, str) else tuple(str(f) for f in forms)
        )
        cik_tuple = (
            (str(ciks),)
            if isinstance(ciks, (str, int))
            else tuple(str(c) for c in ciks)
        )
        suffix_tuple = (
            (suffixes,)
            if isinstance(suffixes, str)
            else tuple(str(s) for s in suffixes)
        )
        spec = TargetSpec(
            forms=form_tuple,
            ciks=cik_tuple,
            dates=dates,
            suffixes=suffix_tuple,
            role=role,
            limit=limit,
        )
        options = RunnerOptions(
            operation=operation,
            family_operations=family_operations or {},
            workers=self.workers,
            sec_client=self.sec_client,
            artifacts_root=self.artifacts_root,
        )
        runner = PipelineRunner(options)
        return runner.run(spec)

    def fetch_from_file(
        self,
        file_path: Path | str,
        *,
        operation: str = "raw",
        family_operations: dict[str, str] | None = None,
        role: str = "primary",
    ) -> FilingsResult:
        """Execute end-to-end acquisition against an arbitrary DuckDB-readable file."""
        spec = TargetSpec(
            role=role,
            input_file=Path(file_path),
        )
        options = RunnerOptions(
            operation=operation,
            family_operations=family_operations or {},
            workers=self.workers,
            sec_client=self.sec_client,
            artifacts_root=self.artifacts_root,
        )
        runner = PipelineRunner(options)
        return runner.run(spec)


__all__ = ["Edgar"]
