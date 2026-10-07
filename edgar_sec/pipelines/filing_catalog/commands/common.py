"""Shared CLI helper functions for filing catalog commands."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def emit_progress(event: dict[str, Any]) -> None:
    """Write human-readable progress to stderr."""
    stage = event.get("stage", "")
    rows = event.get("rows")
    suffix = f" ({rows} rows)" if isinstance(rows, int) else ""
    print(f"[filing-catalog] {stage}{suffix}", file=sys.stderr)


def resolve_artifacts(value: str) -> Path | None:
    """Resolve an optional artifacts root path override."""
    return Path(value).resolve() if value else None
