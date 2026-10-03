"""How this pipeline's progress events are rendered.

The contract under test is that every long command is visibly progressing, and
that a captured log stays readable and unambiguous. Two properties are important
and are pinned directly: the phase is named on every emitted line, and a non-TTY
run never receives bar control characters.

The ``close()`` test exists because of a real defect. Closing the fetch and
starting the merge were one method, so closing a run that never reached its merge
opened a merge bar nobody had entered.
"""

from __future__ import annotations

import sys

import pytest

from edgar_sec.pipelines.metadata_sync.progress import (
    AUGMENT_MERGE_STAGES,
    MERGE_PROGRESS_STAGES,
    AugmentProgress,
    emit_progress_event,
    progress_renderer,
)


class _Stream:
    """A stderr stand-in that reports a chosen ``isatty`` and forwards writes.

    ``sys.stderr`` is already pytest's capture object here, so forwarding keeps
    ``capsys`` working. Patching ``isatty`` on it directly is not an option: it is
    a text stream, not a module, so there is nothing to attach the attribute to.
    """

    def __init__(self, wrapped: object, tty: bool) -> None:
        self._wrapped = wrapped
        self._tty = tty

    def write(self, text: str) -> int:
        return self._wrapped.write(text)  # type: ignore[attr-defined]

    def flush(self) -> None:
        self._wrapped.flush()  # type: ignore[attr-defined]

    def isatty(self) -> bool:
        return self._tty


def _set_tty(monkeypatch: pytest.MonkeyPatch, tty: bool) -> None:
    monkeypatch.setattr(
        "edgar_sec.pipelines.metadata_sync.progress.sys.stderr",
        _Stream(sys.stderr, tty),
    )


def _not_a_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_tty(monkeypatch, False)


def _a_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_tty(monkeypatch, True)


# --------------------------------------------------------------- the log path


def test_a_fetch_event_is_not_labelled_as_a_merge_stage(capsys) -> None:
    """The log renderer hardcoded ``merge:``, which mislabelled fetch events.

    A redirected ``run`` logged ``merge: ok`` per CIK, so a log consumer could not
    tell the fetch phase from the merge phase it was reading.
    """
    emit_progress_event({"type": "cik_normalized", "cik": "0000001985"})
    assert "fetch: cik_normalized" in capsys.readouterr().err


@pytest.mark.parametrize(
    "event_type",
    ["merge_stage", "readback_done", "chunks_validated", "cik_index"],
)
def test_merge_shaped_events_name_the_merge_phase(capsys, event_type: str) -> None:
    emit_progress_event({"type": event_type})
    assert f"merge: {event_type}" in capsys.readouterr().err


def test_a_row_count_is_carried_into_the_line(capsys) -> None:
    emit_progress_event({"type": "readback_done", "rows": 12})
    assert "merge: readback_done (12 rows)" in capsys.readouterr().err


def test_a_caller_can_override_the_phase_label(capsys) -> None:
    emit_progress_event({"type": "cik_normalized"}, label="fetch")
    assert "fetch: cik_normalized" in capsys.readouterr().err


# ------------------------------------------------------- the single-phase path


def test_a_piped_command_emits_lines_and_builds_no_bar(monkeypatch, capsys) -> None:
    _not_a_tty(monkeypatch)
    progress, bar = progress_renderer("fetch", 3, desc="plan abc")
    assert bar is None
    progress({"type": "cik_normalized", "cik": "1"})
    assert "fetch: cik_normalized" in capsys.readouterr().err


def test_a_terminal_command_builds_a_bar_it_can_close(monkeypatch) -> None:
    _a_tty(monkeypatch)
    progress, bar = progress_renderer("fetch", 3, desc="plan abc")
    assert progress is not None
    assert bar is not None
    bar.close()


def test_a_terminal_merge_builds_a_stage_bar_it_can_close(monkeypatch) -> None:
    """The merge branch must return its bar, or the caller's close never fires."""
    _a_tty(monkeypatch)
    progress, bar = progress_renderer("merge", MERGE_PROGRESS_STAGES, desc="merge abc")
    assert progress is not None
    assert bar is not None
    bar.close()


# ------------------------------------------------------------- the two phases


def test_a_piped_router_labels_each_phase(monkeypatch, capsys) -> None:
    """One command, two phases: the log must show which one is running."""
    _not_a_tty(monkeypatch)
    router = AugmentProgress("augment abcd")

    router({"type": "delta_plan", "plan_id": "p", "row_count": 4})
    router({"type": "cik_normalized", "cik": "1", "status": "ok"})
    router({"type": "merge_stage", "stage": "validating"})
    router({"type": "readback_done", "rows": 9})
    router.close()

    err = capsys.readouterr().err
    assert "fetch: delta_plan" in err
    assert "fetch: cik_normalized" in err
    assert "merge: merge_stage" in err
    assert "merge: readback_done (9 rows)" in err


def test_a_piped_router_creates_no_bar(monkeypatch) -> None:
    """A captured log must not receive bar control characters."""
    _not_a_tty(monkeypatch)
    router = AugmentProgress("augment abcd")
    router({"type": "delta_plan", "plan_id": "p", "row_count": 4})
    router({"type": "merge_stage", "stage": "validating"})
    router.close()
    assert router._fetch_bar is None
    assert router._merge_bar is None


def test_the_fetch_bar_is_sized_from_the_announced_delta(monkeypatch) -> None:
    _a_tty(monkeypatch)
    router = AugmentProgress("augment abcd")
    router({"type": "delta_plan", "plan_id": "p", "row_count": 7})
    assert router._fetch_bar is not None
    assert router._fetch_bar.total == 7
    router.close()


def test_the_merge_bar_replaces_the_fetch_bar_instead_of_stacking(
    monkeypatch,
) -> None:
    """Two live bars overlap and overwrite each other's line."""
    _a_tty(monkeypatch)
    router = AugmentProgress("augment abcd")
    router({"type": "delta_plan", "plan_id": "p", "row_count": 7})
    router({"type": "merge_stage", "stage": "validating"})
    assert router._fetch_bar is None
    assert router._merge_bar is not None
    assert router._merge_bar.total == AUGMENT_MERGE_STAGES
    router.close()


def test_closing_a_run_that_never_reached_its_merge_opens_nothing(
    monkeypatch,
) -> None:
    """A failure during the fetch must not leave a merge bar behind.

    A merge bar is a promise of work, and showing one for a command that failed is
    the sort of thing that makes a failure look like a hang.
    """
    _a_tty(monkeypatch)
    router = AugmentProgress("augment abcd")
    router({"type": "delta_plan", "plan_id": "p", "row_count": 7})
    assert router._fetch_bar is not None
    router.close()
    assert router._fetch_bar is None
    assert router._merge_bar is None


def test_closing_a_router_that_never_started_anything_is_safe(monkeypatch) -> None:
    _a_tty(monkeypatch)
    router = AugmentProgress("augment abcd")
    router.close()
    assert router._merge_bar is None
