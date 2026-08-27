"""Typed run options and defaults for the metadata phase."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_INPUT = "uploads/cik-sec.csv"
DEFAULT_ARTIFACTS = ".artifacts/metadata/runs/local"
DEFAULT_PREVIEW_ARTIFACTS = ".artifacts/metadata/preview/local"
DEFAULT_OUTPUT = "phases/01_metadata_extraction/output/merged/submission_metadata.parquet"
DEFAULT_RATE_LIMIT_RPS = 4.0  # conservative per-process target
DEFAULT_WORKERS = 4
DEFAULT_TIMEOUT_S = 15.0
DEFAULT_MAX_RETRIES = 4
DEFAULT_CHUNK_SIZE = 1000
# A URL that exhausted its whole retry budget this many independent runs is
# treated as permanently dead by later sessions (ledger preflight).
DEFAULT_MAX_FAILURE_ATTEMPTS = 3


def rate_limit_to_interval(requests_per_second: float) -> float:
    """Convert a target request rate into the limiter's minimum interval."""
    if requests_per_second <= 0:
        raise ValueError("rate_limit must be positive")
    return 1.0 / requests_per_second


def default_user_agent() -> str:
    return os.environ.get("SEC_USER_AGENT", "")


@dataclass
class RunOptions:
    """Configuration values for a metadata run. Contact identity must be
    configured, never generated randomly."""

    input_path: str = DEFAULT_INPUT
    artifacts_dir: str = DEFAULT_ARTIFACTS
    chunk_size: int = DEFAULT_CHUNK_SIZE
    chunk_id: int | None = None
    workers: int = DEFAULT_WORKERS
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_retries: int = DEFAULT_MAX_RETRIES
    rate_limit_rps: float = DEFAULT_RATE_LIMIT_RPS
    user_agent: str = field(default_factory=default_user_agent)
    cache_dir: str = field(default_factory=lambda: os.environ.get("SEC_CACHE_DIR", ""))
    max_failure_attempts: int = DEFAULT_MAX_FAILURE_ATTEMPTS
    ignore_failure_history: bool = False
    limit: int | None = None
    log_level: str = "INFO"
    run_id: str = "local"

    def validate(self) -> None:
        if self.workers < 1:
            raise ValueError("workers must be >= 1")
        if self.chunk_size < 1:
            raise ValueError("chunk_size must be >= 1")
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if self.max_failure_attempts < 0:
            raise ValueError("max_failure_attempts must be >= 0")
        if not self.user_agent or "@" not in self.user_agent:
            raise ValueError(
                "SEC contact identity is required: set --user-agent or SEC_USER_AGENT to "
                "'AppName/1.0 your-email@example.com'"
            )

    def to_dict(self) -> dict:
        return {
            "input_path": self.input_path,
            "artifacts_dir": self.artifacts_dir,
            "chunk_size": self.chunk_size,
            "workers": self.workers,
            "timeout_s": self.timeout_s,
            "max_retries": self.max_retries,
            "rate_limit_rps": self.rate_limit_rps,
            "user_agent": self.user_agent,
            "cache_dir": self.cache_dir,
            "max_failure_attempts": self.max_failure_attempts,
            "ignore_failure_history": self.ignore_failure_history,
            "limit": self.limit,
            "log_level": self.log_level,
            "run_id": self.run_id,
        }
