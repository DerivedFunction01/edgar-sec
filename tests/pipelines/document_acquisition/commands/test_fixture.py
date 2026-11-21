from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from edgar_sec.pipelines.document_acquisition import cli
from edgar_sec.pipelines.document_acquisition.commands import fixture
from edgar_sec.pipelines.document_acquisition.fixture_store.discovery import (
    FixtureSummary,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.models import (
    FixturePlanCaptureResult,
    FixturePlanPin,
)


class _Transport:
    def __init__(self, _factory):
        self.closed = False

    def close(self):
        self.closed = True


def test_fixture_create_delegates_and_emits_stable_json(capsys, tmp_path, monkeypatch):
    calls = []
    fixture_root = tmp_path / "fixtures" / "fixture-1"
    monkeypatch.setattr(
        fixture,
        "create_fixture",
        lambda fixture_id, pin, *, paths: (
            calls.append((fixture_id, pin, paths.artifacts_root)) or fixture_root
        ),
    )
    plan = SimpleNamespace(
        plan_id="plan-1",
        manifest={"plan_digest": "a" * 64, "target_schema_version": 1},
    )
    monkeypatch.setattr(fixture, "read_published_plan", lambda *_args: plan)
    monkeypatch.setattr(
        fixture,
        "resolve_document_planning_paths",
        lambda **_kwargs: object(),
    )

    result = cli.main(
        [
            "fixture",
            "create",
            "--fixture",
            "fixture-1",
            "--plan-id",
            "plan-1",
            "--artifacts",
            str(tmp_path),
            "--json",
        ]
    )

    assert result == 0
    assert calls == [
        (
            "fixture-1",
            FixturePlanPin("plan-1", "a" * 64, 1),
            tmp_path.resolve(),
        )
    ]
    assert json.loads(capsys.readouterr().out) == {
        "command": "fixture create",
        "fixture_id": "fixture-1",
        "path": str(fixture_root),
        "status": "created",
    }


def test_fixture_fill_requires_explicit_network_permission(
    capsys, tmp_path, monkeypatch
):
    monkeypatch.setattr(fixture, "_LazySecTransport", _Transport)
    monkeypatch.setattr(
        fixture,
        "capture_fixture_plan",
        lambda *_args, **_kwargs: pytest.fail("network fetch must not start"),
    )

    result = cli.main(
        [
            "fixture",
            "fill",
            "--fixture",
            "fixture-1",
            "--json",
            "--artifacts",
            str(tmp_path),
        ]
    )

    assert result == 1
    assert json.loads(capsys.readouterr().out) == {
        "command": "fixture fill",
        "error": "pass --allow-network to fetch fixture inputs",
        "status": "error",
    }


def test_fixture_fill_captures_plan_targets_and_emits_counts(
    capsys, tmp_path, monkeypatch
) -> None:
    calls = []
    transport = _Transport(None)
    pin = FixturePlanPin("plan-1", "a" * 64, 1)
    monkeypatch.setattr(fixture, "_LazySecTransport", lambda _factory: transport)
    monkeypatch.setattr(fixture, "sec_transport_factory", lambda: None)
    monkeypatch.setattr(fixture, "response_byte_limit", lambda _value: 4096)
    monkeypatch.setattr(
        fixture,
        "resolve_acquisition_paths",
        lambda **_kwargs: SimpleNamespace(artifacts_root=tmp_path.resolve()),
    )
    monkeypatch.setattr(fixture, "fixture_plan_pin", lambda *_args: pin)

    def capture(
        fixture_id,
        *,
        paths,
        max_body_bytes,
        transport,
        limit,
        on_target,
        workers=None,
    ):
        calls.append(
            (
                fixture_id,
                paths.artifacts_root,
                max_body_bytes,
                transport,
                limit,
                on_target is not None,
            )
        )
        return FixturePlanCaptureResult(
            fixture_id,
            "cap-plan-1",
            3,
            4,
            1,
            2,
            1,
            {"selection_error": 1},
        )

    monkeypatch.setattr(fixture, "capture_fixture_plan", capture)
    result = cli.main(
        [
            "fixture",
            "fill",
            "--fixture",
            "fixture-1",
            "--plan-id",
            "plan-1",
            "--allow-network",
            "--limit",
            "7",
            "--artifacts",
            str(tmp_path),
            "--json",
            "--no-progress",
        ]
    )

    assert result == 0
    assert calls == [("fixture-1", tmp_path.resolve(), 4096, transport, 7, True)]
    assert transport.closed
    assert json.loads(capsys.readouterr().out) == {
        "capture_id": "cap-plan-1",
        "captured_cases": 3,
        "failed_targets": 1,
        "failure_counts": {"selection_error": 1},
        "fetched_lazy_indexes": 2,
        "fixture_id": "fixture-1",
        "reused_lazy_indexes": 1,
        "skipped_targets": 4,
        "status": "filled",
        "command": "fixture fill",
    }


def test_fixture_list_uses_streaming_discovery_and_filters(
    capsys, tmp_path, monkeypatch
) -> None:
    calls = []
    summaries = [
        FixtureSummary("fixture-1", "plan-1", "a" * 64, 1, 2, 4, 1),
        FixtureSummary("fixture-2", "plan-2", "b" * 64, 1, 1, 1, 0),
    ]

    def fixture_cases(paths, *, fixture_id):
        calls.append((paths.artifacts_root, fixture_id))
        return iter(())

    monkeypatch.setattr(
        fixture, "list_fixture_summaries", lambda _paths: iter(summaries)
    )
    monkeypatch.setattr(fixture, "list_fixture_cases", fixture_cases)

    result = cli.main(
        [
            "fixture",
            "list",
            "--fixture",
            "fixture-2",
            "--artifacts",
            str(tmp_path),
            "--json",
        ]
    )

    assert result == 0
    assert calls == [(tmp_path.resolve(), "fixture-2")]
    assert json.loads(capsys.readouterr().out) == {
        "cases": [],
        "command": "fixture list",
        "fixtures": [
            {
                "case_count": 1,
                "capture_count": 1,
                "fixture_id": "fixture-2",
                "lazy_index_count": 0,
                "target_plan_digest": "b" * 64,
                "target_plan_id": "plan-2",
                "target_plan_schema_version": 1,
            }
        ],
        "status": "ok",
    }


def test_fixture_replay_is_not_a_user_command() -> None:
    with pytest.raises(SystemExit):
        cli.main(["fixture", "replay", "--fixture", "fixture-1"])
