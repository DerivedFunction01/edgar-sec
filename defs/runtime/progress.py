"""Shared tqdm adapters for phase progress events."""

from __future__ import annotations

import time
from collections.abc import Callable

from tqdm import tqdm


def make_tqdm_callback(
    pbar, started: float | None = None, *, warning: Callable[[str], None] | None = None
):
    """Adapt generic ``cik_done``/``worker_failed`` events to a tqdm bar."""
    started = time.monotonic() if started is None else started
    state = {"ok": 0, "not_ok": 0, "hist": 0}

    def callback(event: dict) -> None:
        metrics = event.get("metrics") or {}
        if event.get("type") == "worker_failed":
            state["not_ok"] += 1
            (warning or (lambda message: tqdm.write(message)))(
                f"worker failed: {event.get('error', 'unknown error')}"
            )
        else:
            if event.get("status") == "ok":
                state["ok"] += 1
            else:
                state["not_ok"] += 1
            state["hist"] += event.get("historical_files", 0) or 0
            pbar.update(1)
        requests = metrics.get("requests_total", 0)
        elapsed = max(time.monotonic() - started, 1e-6)
        postfix = {
            "ok": state["ok"],
            "fail": state["not_ok"],
            "hist": state["hist"],
            "req": requests,
            "rps": f"{requests / elapsed:.1f}",
            "retry": metrics.get("retries_used", 0),
            "throttle": metrics.get("throttled_count", 0),
        }
        if metrics.get("cache_hits"):
            postfix["cache"] = metrics["cache_hits"]
        pbar.set_postfix(postfix)

    return callback


__all__ = ["make_tqdm_callback"]
