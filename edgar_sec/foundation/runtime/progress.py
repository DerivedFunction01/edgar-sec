"""Tqdm progress bar adapters for pipeline and batch execution."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from tqdm import tqdm


def make_tqdm_callback(
    pbar: tqdm,
    started: float | None = None,
    *,
    warning: Callable[[str], None] | None = None,
) -> Callable[[dict[str, Any]], None]:
    """Adapt generic pipeline execution events to a tqdm progress bar with throughput stats."""
    start_time = time.monotonic() if started is None else started
    state = {"ok": 0, "fail": 0, "hist": 0}

    def callback(event: dict[str, Any]) -> None:
        metrics = event.get("metrics") or {}
        event_type = event.get("type", "")

        if event_type == "worker_failed":
            state["fail"] += 1
            msg = f"worker failed: {event.get('error', 'unknown error')}"
            if warning:
                warning(msg)
            else:
                tqdm.write(msg)
        else:
            if event.get("status") in ("ok", "cached"):
                state["ok"] += 1
            else:
                state["fail"] += 1
            state["hist"] += int(event.get("historical_files", 0) or 0)
            pbar.update(1)

        postfix = {
            "ok": state["ok"],
            "fail": state["fail"],
            "hist": state["hist"],
        }
        if metrics:
            requests = metrics.get("requests_total", 0)
            elapsed = max(time.monotonic() - start_time, 1e-6)
            postfix.update(
                {
                    "req": requests,
                    "rps": f"{requests / elapsed:.1f}",
                    "retry": metrics.get("retries_used", 0),
                    "throttle": metrics.get("throttled_count", 0),
                }
            )
            if metrics.get("cache_hits"):
                postfix["cache"] = metrics["cache_hits"]
        pbar.set_postfix(postfix)

    return callback


def make_merge_progress_callback(pbar: tqdm) -> Callable[[dict[str, Any]], None]:
    """Adapt partition merge and validation events to a tqdm progress bar."""

    def callback(event: dict[str, Any]) -> None:
        event_type = event.get("type", "")
        if event_type in ("partition_validated", "merge_stage"):
            pbar.update(1)
        elif event_type == "readback_done":
            rows = event.get("rows", 0)
            pbar.set_postfix({"verified_rows": rows})

    return callback


__all__ = ["make_merge_progress_callback", "make_tqdm_callback"]
