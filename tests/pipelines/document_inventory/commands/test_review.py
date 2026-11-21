from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from edgar_sec.pipelines.document_inventory.commands import review as review_command
from edgar_sec.pipelines.document_inventory.review_artifacts.models import (
    ReviewRunResult,
    ReviewSummary,
)


def test_review_command_shows_case_progress_on_tty(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    bars = []

    class Bar:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            self.total = kwargs["total"]
            self.count = 0
            self.refreshed = False
            self.closed = False
            bars.append(self)

        def __bool__(self) -> bool:
            if self.total is None:
                raise TypeError("bool() undefined when iterable == total == None")
            return self.total > 0

        def refresh(self) -> None:
            self.refreshed = True

        def update(self, count: int) -> None:
            self.count += count

        def set_postfix(self, _values: dict) -> None:
            return None

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(review_command, "tqdm", Bar)
    monkeypatch.setattr(
        review_command,
        "sys",
        SimpleNamespace(stderr=SimpleNamespace(isatty=lambda: True)),
    )

    def build(_fixture, _output, *, progress_callback, **_kwargs):
        progress_callback({"type": "start", "total": 2})
        progress_callback({"type": "outcome", "status": "ok"})
        progress_callback({"type": "outcome", "status": "failed"})
        return ReviewRunResult(
            "review-1",
            tmp_path / "review",
            ReviewSummary(2, 1, 1, 0, 0, 0, 1, 1),
            1,
        )

    monkeypatch.setattr(review_command, "build_review_artifacts", build)
    args = SimpleNamespace(
        artifacts_root=str(tmp_path),
        fixture="fixture-1",
        output=str(tmp_path / "review"),
        accession=None,
        limit=None,
        workers=1,
        json=False,
        no_progress=False,
    )

    assert review_command.cmd_review_artifacts(args) == 1
    assert len(bars) == 1
    assert bars[0].kwargs["desc"] == "Review"
    assert bars[0].kwargs["unit"] == "case"
    assert bars[0].total == 2
    assert bars[0].refreshed
    assert bars[0].count == 2
    assert bars[0].closed
    capsys.readouterr()


@pytest.mark.parametrize(
    ("tty", "json_output", "no_progress"),
    [(True, False, True), (True, True, False), (False, False, False)],
)
def test_review_command_suppresses_progress_when_requested(
    tmp_path: Path, monkeypatch, capsys, tty: bool, json_output: bool, no_progress: bool
) -> None:
    bars = []
    monkeypatch.setattr(review_command, "tqdm", lambda **kwargs: bars.append(kwargs))
    monkeypatch.setattr(
        review_command,
        "sys",
        SimpleNamespace(stderr=SimpleNamespace(isatty=lambda: tty)),
    )
    callbacks = []

    def build(_fixture, _output, *, progress_callback, **_kwargs):
        callbacks.append(progress_callback)
        return ReviewRunResult(
            "review-1",
            tmp_path / "review",
            ReviewSummary(1, 1, 0, 0, 0, 0, 1, 0),
            0,
        )

    monkeypatch.setattr(review_command, "build_review_artifacts", build)
    args = SimpleNamespace(
        artifacts_root=str(tmp_path),
        fixture="fixture-1",
        output=str(tmp_path / "review"),
        accession=None,
        limit=None,
        workers=1,
        json=json_output,
        no_progress=no_progress,
    )

    assert review_command.cmd_review_artifacts(args) == 0
    assert not bars
    assert callbacks == [None]
    capsys.readouterr()
