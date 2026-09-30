"""How this pipeline's progress events become something a person can watch.

Extracted from ``cli.py`` for ownership rather than only for length. ``cli.py``
owns the argparse surface and the ``cmd_*`` callables that the CLI and the wizard
both invoke; a renderer calls none of those and is called by none of them, so it
is not part of that contract. It is presentation, and presentation had no home in
this package until now.

It is deliberately phase-local rather than shared. ``foundation.runtime.progress``
already owns the adapters that turn a pipeline's events into a tqdm bar, and it
knows nothing about which phase a pipeline is in. What lives here is the phase
knowledge: that this pipeline has a per-CIK fetch shape, a per-stage merge shape,
and that an augmentation runs both in one command. Promoting that to
``foundation`` on the strength of one caller would be speculative, and the
roadmap already records the failure mode -- v1's shared ``run_interactive``
"hardcoded Phase 01's exact model ... [and] became dead code outside Phase 01".
If a second pipeline needs the same sequencing, promote it then, with two callers
to shape it.

A terminal gets a live bar; a pipe or a captured log gets one plain line per event
prefixed with the phase that emitted it. Choosing on ``isatty`` is what keeps a
redirected run readable, and naming the phase is what keeps a log parseable: the
two shapes are otherwise indistinguishable, and a log consumer cannot tell a
fetch event from a merge stage.
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

# An augmentation emits its own two merge stages (validating, publishing_parts).
# They are counted here rather than inferred, so a bar that finishes short is
# visible instead of looking like a hang.
AUGMENT_MERGE_STAGES = 2

# Event types that belong to the merge half rather than the fetch half.
_MERGE_EVENTS = frozenset(
    {"merge_stage", "readback_done", "chunks_validated", "cik_index"}
)


def _event_phase(event_type: str) -> str:
    return "merge" if event_type in _MERGE_EVENTS else "fetch"


def emit_progress_event(event: dict[str, Any], label: str = "") -> None:
    """Render one progress event to stderr.

    Progress goes to stderr because merge output owns stdout, and a non-TTY run
    stays quiet rather than emitting bar control characters into a captured log.

    The phase is derived from the event unless the caller supplies one. It used to
    print a hardcoded ``merge:`` prefix, which mislabelled the per-CIK fetch events
    ``run`` emits as if they were merge stages, so a redirected ``run`` logged
    ``merge: ok`` once per CIK and a log consumer could not tell the phases apart.
    """
    event_type = event.get("type", "progress")
    rows = event.get("rows")
    detail = f" ({rows} rows)" if rows is not None else ""
    print(f"{label or _event_phase(event_type)}: {event_type}{detail}", file=sys.stderr)


def progress_renderer(
    kind: str, total: int, *, desc: str
) -> tuple[Callable[[dict[str, Any]], None] | None, Any]:
    """Build a progress callback for a single-phase command, and its bar to close.

    The tqdm adapters in ``foundation.runtime.progress`` already implement both
    event shapes this pipeline emits: per-CIK fetch events and per-stage merge
    events. Routing through them gives those adapters a real caller and keeps the
    rendering in one place instead of per command.
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

    An augmentation is the only long command that runs two phases end to end: a
    rate-limited fetch of the delta, then a merge that scans every input for null
    and duplicate CIKs before publishing parts. ``run`` and ``merge`` each get a
    single bar because each is a single phase.

    The fetch bar cannot be sized before the call, because the delta depends on
    which CIKs the base snapshot already holds and only the augmentation knows
    that. So the augmentation announces its plan with a ``delta_plan`` event and
    the bar is sized from it, which is why this is a router rather than one of the
    single-phase renderers.

    A pipe or a captured log gets the plain event lines for both phases, so a
    non-interactive caller sees the same stream ``run`` and ``merge`` produce.
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

        Separated from ``_close_fetch`` because a failure during the fetch has to
        leave nothing behind: closing the run must not open a merge bar nobody
        entered, and an operator who abandons the command should not get one.
        """
        self._close_fetch()
        if self._merge_bar is not None:
            self._merge_bar.close()
        self._merge_bar = None
        self._merge_callback = None
