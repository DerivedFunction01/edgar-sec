"""How this pipeline's progress events become something a person can watch.
A terminal gets a live bar; a pipe or captured log gets one plain line per event
prefixed by the emitting phase, so a log consumer can tell a fetch event from a
merge stage.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

__all__ = [
    "AUGMENT_MERGE_STAGES",
    "MERGE_PROGRESS_STAGES",
    "AugmentProgress",
    "emit_progress_event",
    "progress_renderer",
]

# ``merge_chunks`` emits one progress event per stage, and the stage count is part
# of the contract the merge-reporting callback already understands.
MERGE_PROGRESS_STAGES = 4

# An augmentation emits its own two merge stages. Counted rather than inferred,
# so a bar that finishes short is visible instead of looking like a hang.
AUGMENT_MERGE_STAGES = 2

# Event types that belong to the merge half rather than the fetch half.
_MERGE_EVENTS = frozenset(
    {"merge_stage", "readback_done", "chunks_validated", "cik_index"}
)


def _event_phase(event_type: str) -> str:
    return "merge" if event_type in _MERGE_EVENTS else "fetch"


def emit_progress_event(event: dict[str, Any], label: str = "") -> None:
    """Render one progress event to stderr.
    The phase is derived from the event, or a redirected run mislabels fetches.
    """
    event_type = event.get("type", "progress")
    rows = event.get("rows")
    detail = f" ({rows} rows)" if rows is not None else ""
    print(f"{label or _event_phase(event_type)}: {event_type}{detail}", file=sys.stderr)


def progress_renderer(
    kind: str, total: int, *, desc: str
) -> tuple[Callable[[dict[str, Any]], None] | None, Any]:
    """Build a progress callback for a single-phase command, and its bar to close.

    Routes through the shared tqdm adapters so rendering stays in one place.
    """
    if not sys.stderr.isatty():
        return (lambda event: emit_progress_event(event, label=kind)), None
    from tqdm import tqdm

    if kind == "merge":
        from edgar_sec.foundation.runtime.progress import make_merge_progress_callback

        bar = tqdm(total=total, unit="stage", desc=desc, leave=False)
        return make_merge_progress_callback(bar), bar
    from edgar_sec.foundation.runtime.progress import make_tqdm_callback

    bar = tqdm(total=total, unit="cik", desc=desc, leave=False)
    return make_tqdm_callback(bar), bar


class AugmentProgress:
    """Route one augmentation's two phases to their own progress presentation.
    The fetch bar is sized from the ``delta_plan`` event, hence a router rather than
    a single-phase renderer.
    """

    def __init__(self, desc: str) -> None:
        self._desc = desc
        self._fetch_bar: Any = None
        self._fetch_callback: Callable[[dict[str, Any]], None] | None = None
        self._merge_bar: Any = None
        self._merge_callback: Callable[[dict[str, Any]], None] | None = None
        self._log_only = not sys.stderr.isatty()
        self._phase = "fetch"

    def __call__(self, event: dict[str, Any]) -> None:
        if self._log_only:
            event_type = event.get("type", "")
            if event_type == "merge_stage":
                self._phase = "merge"
            emit_progress_event(event, label=self._phase)
            return
        event_type = event.get("type", "")
        if event_type == "delta_plan":
            self._start_fetch(int(event.get("row_count", 0) or 0))
            return
        if event_type == "merge_stage" and self._fetch_bar is not None:
            # The fetch is finished; release its bar before the merge opens its
            # own, so two live bars never overlap and the merge starts on a clean
            # line rather than on top of the fetch bar.
            self._close_fetch()
            self._start_merge()
        if self._merge_callback is not None and event_type in {
            "merge_stage",
            "readback_done",
        }:
            self._merge_callback(event)
            return
        if self._fetch_callback is not None:
            self._fetch_callback(event)

    def _start_fetch(self, row_count: int) -> None:
        from tqdm import tqdm

        from edgar_sec.foundation.runtime.progress import make_tqdm_callback

        self._fetch_bar = tqdm(
            total=row_count, unit="cik", desc=f"{self._desc} fetch", leave=False
        )
        self._fetch_callback = make_tqdm_callback(self._fetch_bar)

    def _start_merge(self) -> None:
        from tqdm import tqdm

        from edgar_sec.foundation.runtime.progress import make_merge_progress_callback

        self._merge_bar = tqdm(
            total=AUGMENT_MERGE_STAGES,
            unit="stage",
            desc=f"{self._desc} merge",
            leave=False,
        )
        self._merge_callback = make_merge_progress_callback(self._merge_bar)

    def _close_fetch(self) -> None:
        if self._fetch_bar is not None:
            self._fetch_bar.close()
        self._fetch_bar = None
        self._fetch_callback = None

    def close(self) -> None:
        """Release whichever bar is open. Must not start one.

        Closing after a failed fetch must not open a merge bar nobody entered.
        """
        self._close_fetch()
        if self._merge_bar is not None:
            self._merge_bar.close()
        self._merge_bar = None
        self._merge_callback = None
