"""Generic filesystem discovery for plan bundles."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from edgar_sec.foundation.runtime.paths import PLAN_FILE_NAME
from .envelope import PlanEnvelope

E = TypeVar("E", bound=PlanEnvelope)


def read_plan_envelope(
    manifest_or_dir: str | Path,
    *,
    envelope_cls: type[E] = PlanEnvelope,  # type: ignore[assignment]
) -> E | None:
    """Read one plan bundle envelope, returning None if unreadable or invalid."""
    path = Path(manifest_or_dir)
    manifest_file = path if path.is_file() else path / PLAN_FILE_NAME
    if not manifest_file.is_file():
        return None
    try:
        data = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    plan_id = str(data.get("plan_id") or "").strip()
    if not plan_id:
        return None
    return envelope_cls(plan_id=plan_id, manifest_path=manifest_file, raw=data)


def discover_plans(
    plans_root: str | Path,
    *,
    filter_fn: Callable[[E], bool] | None = None,
    envelope_cls: type[E] = PlanEnvelope,  # type: ignore[assignment]
) -> list[E]:
    """Discover every valid plan bundle in a plans root directory."""
    root = Path(plans_root)
    if not root.is_dir():
        return []

    found: list[tuple[float, E]] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        envelope = read_plan_envelope(entry, envelope_cls=envelope_cls)
        if envelope is None:
            continue
        if filter_fn is not None and not filter_fn(envelope):
            continue
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            mtime = 0.0
        found.append((mtime, envelope))

    found.sort(key=lambda pair: (pair[0], pair[1].plan_id), reverse=True)
    return [envelope for _, envelope in found]
