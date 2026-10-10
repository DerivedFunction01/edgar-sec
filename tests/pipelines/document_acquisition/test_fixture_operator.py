from __future__ import annotations

import hashlib
import io
import json
import sqlite3
from datetime import UTC, datetime

import pytest

from edgar_sec.infra.sec_http.streaming import StreamFailure
from edgar_sec.foundation.serialization import canonical_hash, canonical_json
from edgar_sec.pipelines.document_acquisition.fixture_operator import (
    FixtureOperationError,
    capture_fixture_case,
    create_fixture,
    list_fixture_cases,
    replay_fixture_case,
)
from edgar_sec.pipelines.document_acquisition import cli
from edgar_sec.pipelines.document_acquisition.commands import run as run_command
from edgar_sec.pipelines.document_acquisition.fixture_store.storage import (
    append_fixture_case,
    initialize_fixture,
)
from edgar_sec.pipelines.document_acquisition.models import AcquisitionPolicy
from edgar_sec.pipelines.document_acquisition.run_state.evidence import (
    get_attempt_evidence_group,
)
from edgar_sec.pipelines.document_acquisition.run_state.store import (
    get_target_state,
)
from edgar_sec.pipelines.document_acquisition.runner import execute_acquisition_run
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from tests.pipelines.document_acquisition.test_runner import (
    _BUNDLE_URL,
    _INDEX,
    _INDEX_URL,
    _UNLINKED_INDEX,
    _MemoryTransport,
    _make_run,
)


def _execute_run(
    paths,
    run_id,
    row,
    responses,
    monkeypatch,
    *,
    failures=None,
    retry_failures=False,
    retain_response_evidence=False,
):
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.runner.derive_resources",
        lambda: type("Resources", (), {"workers": 1, "worker_ceiling": 1})(),
    )
    report = execute_acquisition_run(
        run_id,
        retry_failures=retry_failures,
        paths=paths,
        policy=AcquisitionPolicy(
            max_response_bytes=4096,
            retain_response_evidence=retain_response_evidence,
        ),
        transport=_MemoryTransport(responses, failures=failures),
        clock=lambda: datetime(2025, 1, 1, tzinfo=UTC),
    )
    state = get_target_state(paths.run_state_path(run_id), "target-1")
    assert state is not None
    return report, state


def _initial_attempt_id(paths, run_id):
    with sqlite3.connect(paths.run_state_path(run_id)) as connection:
        return connection.execute(
            "SELECT attempt_id FROM attempts WHERE target_id = ? "
            "AND attempt_kind = 'document_body' ORDER BY attempt_number LIMIT 1",
            ("target-1",),
        ).fetchone()[0]


def test_capture_direct_attempt_is_idempotent_and_replays_without_network(
    tmp_path, monkeypatch
) -> None:
    paths, run_id, row = _make_run(tmp_path, lazy=False)
    body = b"<html>captured filing</html>"
    _execute_run(paths, run_id, row, {row["target_url"]: body}, monkeypatch)
    fixture_root = create_fixture("fixture-1", paths=paths)
    state = get_target_state(paths.run_state_path(run_id), "target-1")
    assert state is not None and state.last_attempt_id is not None

    first = capture_fixture_case(
        "fixture-1",
        run_id,
        "target-1",
        state.last_attempt_id,
        paths=paths,
        max_response_bytes=4096,
    )
    second = capture_fixture_case(
        "fixture-1",
        run_id,
        "target-1",
        state.last_attempt_id,
        paths=paths,
        max_response_bytes=4096,
    )
    cases = list(list_fixture_cases(paths, fixture_id="fixture-1"))
    output = tmp_path / "replayed.html"
    replay = replay_fixture_case(
        "fixture-1", first.capture_id, "target-1", output, paths=paths
    )

    assert fixture_root.is_dir()
    assert first.capture_id == second.capture_id
    assert first.reused_response is False
    assert second.reused_response is True
    assert len(cases) == 1
    assert cases[0].acquisition_status == "acquired"
    assert cases[0].target_plan_schema_version == "1"
    assert cases[0].selected_filename == "cover.htm"
    assert replay.output_path == output
    assert replay.response_sha256 == first.response_sha256
    assert output.read_bytes() == body
    with pytest.raises(FixtureOperationError, match="already exists"):
        replay_fixture_case(
            "fixture-1", first.capture_id, "target-1", output, paths=paths
        )
    assert output.read_bytes() == body
    with pytest.raises(FixtureOperationError, match="inside managed artifacts"):
        replay_fixture_case(
            "fixture-1",
            first.capture_id,
            "target-1",
            fixture_root / "replayed.bin",
            paths=paths,
        )
    with sqlite3.connect(paths.fixture_database_path("fixture-1")) as connection:
        assert connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 1


@pytest.mark.parametrize("lazy", (False, True))
def test_capture_and_replay_bodyless_failure_as_typed_metadata(
    tmp_path, monkeypatch, lazy: bool
) -> None:
    paths, run_id, row = _make_run(tmp_path, lazy=lazy)
    failure = StreamFailure("http_not_found", False, 404, "not found")
    _execute_run(
        paths,
        run_id,
        row,
        {},
        monkeypatch,
        failures={row["target_url"]: failure},
    )
    fixture_id = f"fixture-failure-{lazy}"
    create_fixture(fixture_id, paths=paths)
    state = get_target_state(paths.run_state_path(run_id), "target-1")
    assert state is not None and state.last_attempt_id is not None

    captured = capture_fixture_case(
        fixture_id,
        run_id,
        "target-1",
        state.last_attempt_id,
        paths=paths,
        max_response_bytes=4096,
    )
    replay = replay_fixture_case(
        fixture_id,
        captured.capture_id,
        "target-1",
        tmp_path / "should-not-exist.html",
        paths=paths,
    )

    assert captured.response_sha256 is None
    assert replay.acquisition_status == "failed"
    assert replay.output_path is None
    assert not (tmp_path / "should-not-exist.html").exists()


@pytest.mark.parametrize("mode", ("bundle", "lazy"))
def test_capture_refuses_unavailable_bundle_or_lazy_response_evidence(
    tmp_path, monkeypatch, mode: str
) -> None:
    if mode == "bundle":
        paths, run_id, row = _make_run(tmp_path, lazy=False, bundle=True)
        responses = {
            row[
                "target_url"
            ]: b"<DOCUMENT><SEQUENCE>2<TYPE>10-K<TEXT>body</TEXT></DOCUMENT>"
        }
    else:
        paths, run_id, row = _make_run(tmp_path, lazy=True)
        selected_url = _INDEX_URL.rsplit("/", 1)[0] + "/report.htm"
        responses = {
            row["target_url"]: b"<html>initial</html>",
            _INDEX_URL: _INDEX,
            selected_url: b"<html>selected</html>",
        }
    _execute_run(paths, run_id, row, responses, monkeypatch)
    create_fixture(f"fixture-{mode}", paths=paths)
    state = get_target_state(paths.run_state_path(run_id), "target-1")
    assert state is not None and state.last_attempt_id is not None

    with pytest.raises(
        FixtureOperationError, match="response evidence is incomplete or not retained"
    ):
        capture_fixture_case(
            f"fixture-{mode}",
            run_id,
            "target-1",
            _initial_attempt_id(paths, run_id),
            paths=paths,
            max_response_bytes=4096,
        )


@pytest.mark.parametrize("mode", ("bundle", "lazy-direct", "lazy-bundle"))
def test_opted_in_response_groups_capture_and_replay(tmp_path, monkeypatch, mode):
    if mode == "bundle":
        paths, run_id, row = _make_run(tmp_path, lazy=False, bundle=True)
        bundle = (
            b"<DOCUMENT><SEQUENCE>2<FILENAME>report.htm<TYPE>10-K<TEXT>bundle body"
            b"</TEXT></DOCUMENT>"
        )
        responses = {row["target_url"]: bundle}
        selected = b"bundle body"
    elif mode == "lazy-direct":
        paths, run_id, row = _make_run(tmp_path, lazy=True)
        selected_url = _INDEX_URL.rsplit("/", 1)[0] + "/report.htm"
        selected = b"<html>selected lazy response</html>"
        index_body = _INDEX
        responses = {
            row["target_url"]: b"<html>initial catalog response</html>",
            _INDEX_URL: index_body,
            selected_url: selected,
        }
    else:
        paths, run_id, row = _make_run(tmp_path, lazy=True)
        selected_url = _BUNDLE_URL
        selected = b"recovered bundle body"
        index_body = _UNLINKED_INDEX
        selected_response = (
            b"<DOCUMENT><SEQUENCE>2<FILENAME>report.htm<TYPE>10-K<TEXT>"
            b"recovered bundle body</TEXT></DOCUMENT>"
        )
        responses = {
            row["target_url"]: b"<html>initial catalog response</html>",
            _INDEX_URL: index_body,
            selected_url: selected_response,
        }
    _execute_run(
        paths,
        run_id,
        row,
        responses,
        monkeypatch,
        retain_response_evidence=True,
    )
    create_fixture(f"fixture-{mode}-retained", paths=paths)
    group = get_attempt_evidence_group(
        paths.run_state_path(run_id), "target-1", _initial_attempt_id(paths, run_id)
    )
    assert group is not None
    initial_attempt_id = group.initial_attempt.attempt_id

    captured = capture_fixture_case(
        f"fixture-{mode}-retained",
        run_id,
        "target-1",
        initial_attempt_id,
        paths=paths,
        max_response_bytes=4096,
    )
    case = next(iter(list_fixture_cases(paths, fixture_id=f"fixture-{mode}-retained")))
    output = tmp_path / f"{mode}-replayed.bin"
    replay = replay_fixture_case(
        f"fixture-{mode}-retained",
        captured.capture_id,
        "target-1",
        output,
        paths=paths,
    )

    assert case.attempt_id == initial_attempt_id
    assert replay.output_path == output
    assert output.read_bytes() == selected
    if mode == "bundle":
        assert case.response_sha256 == hashlib.sha256(bundle).hexdigest()
        assert case.selected_filename == "report.htm"
    else:
        if mode == "lazy-direct":
            selected_url = _INDEX_URL.rsplit("/", 1)[0] + "/report.htm"
            selected_response = selected
            selected_mode = "direct_url"
            index_body = _INDEX
        else:
            selected_mode = "bundle_sequence"
        assert case.retrieval_mode == "direct_url"
        assert (
            case.response_sha256
            == hashlib.sha256(b"<html>initial catalog response</html>").hexdigest()
        )
        assert case.response_sha256 != case.selected_sha256
        assert case.index_response_sha256 == hashlib.sha256(index_body).hexdigest()
        assert (
            case.selected_response_sha256
            == hashlib.sha256(selected_response).hexdigest()
        )
        assert case.selected_sequence == 2
        assert case.selected_retrieval_mode == selected_mode
        assert case.selected_url == selected_url
        assert case.selected_filename == "report.htm"
        assert group.resolution is not None
        assert json.loads(case.matching_entry_ids_json) == list(
            group.resolution.matching_entry_ids
        )
        with sqlite3.connect(
            paths.fixture_database_path(f"fixture-{mode}-retained")
        ) as connection:
            digests = {
                row[0]
                for row in connection.execute(
                    "SELECT response_sha256 FROM response_bodies"
                )
            }
        assert {
            case.response_sha256,
            case.index_response_sha256,
            case.selected_response_sha256,
        } <= digests
        assert (
            len(
                {
                    case.response_sha256,
                    case.index_response_sha256,
                    case.selected_response_sha256,
                }
            )
            == 3
        )


@pytest.mark.parametrize("tamper", ("missing-index", "selected-digest"))
def test_capture_refuses_missing_or_malformed_related_evidence(
    tmp_path, monkeypatch, tamper
):
    paths, run_id, row = _make_run(tmp_path, lazy=True)
    selected_url = _INDEX_URL.rsplit("/", 1)[0] + "/report.htm"
    _execute_run(
        paths,
        run_id,
        row,
        {
            row["target_url"]: b"<html>initial</html>",
            _INDEX_URL: _INDEX,
            selected_url: b"<html>selected</html>",
        },
        monkeypatch,
        retain_response_evidence=True,
    )
    state = get_target_state(paths.run_state_path(run_id), "target-1")
    assert state is not None and state.last_attempt_id is not None
    group = get_attempt_evidence_group(
        paths.run_state_path(run_id), "target-1", _initial_attempt_id(paths, run_id)
    )
    assert group is not None and group.lazy_index_attempt is not None
    if tamper == "missing-index":
        relative = group.lazy_index_attempt.source_body_relative_path
        assert relative is not None
        (paths.run_dir(run_id) / relative).unlink()
        message = "missing or unsafe"
    else:
        assert group.selected_body_attempt is not None
        relative = group.selected_body_attempt.source_body_relative_path
        assert relative is not None
        selected_path = paths.run_dir(run_id) / relative
        selected_path.write_bytes(b"X" * selected_path.stat().st_size)
        message = "response_sha256 does not match"
    create_fixture(f"fixture-malformed-{tamper}", paths=paths)

    with pytest.raises(FixtureOperationError, match=message):
        capture_fixture_case(
            f"fixture-malformed-{tamper}",
            run_id,
            "target-1",
            group.initial_attempt.attempt_id,
            paths=paths,
            max_response_bytes=4096,
        )


def test_failed_retained_lazy_group_replays_metadata_and_verifies_bodies(
    tmp_path, monkeypatch
):
    paths, run_id, row = _make_run(tmp_path, lazy=True)
    selected_url = _INDEX_URL.rsplit("/", 1)[0] + "/report.htm"
    _execute_run(
        paths,
        run_id,
        row,
        {
            row["target_url"]: b"<html>initial failed-group body</html>",
            _INDEX_URL: _INDEX,
        },
        monkeypatch,
        failures={
            selected_url: StreamFailure("http_not_found", False, 404, "not found")
        },
        retain_response_evidence=True,
    )
    initial_attempt_id = _initial_attempt_id(paths, run_id)
    create_fixture("fixture-failed-retained", paths=paths)
    captured = capture_fixture_case(
        "fixture-failed-retained",
        run_id,
        "target-1",
        initial_attempt_id,
        paths=paths,
        max_response_bytes=4096,
    )
    case = next(iter(list_fixture_cases(paths, fixture_id="fixture-failed-retained")))
    output = tmp_path / "failed-lazy-output.bin"

    replay = replay_fixture_case(
        "fixture-failed-retained",
        captured.capture_id,
        "target-1",
        output,
        paths=paths,
    )

    assert case.acquisition_status == "failed"
    assert case.response_sha256 is not None
    assert case.index_response_sha256 == hashlib.sha256(_INDEX).hexdigest()
    assert case.selected_response_sha256 is None
    assert replay.acquisition_status == "failed"
    assert replay.response_sha256 == case.response_sha256
    assert replay.output_path is None
    assert not output.exists()


def test_capture_rejects_an_attempt_outside_the_target(tmp_path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    create_fixture("fixture-missing", paths=paths)

    with pytest.raises(ValueError):
        capture_fixture_case(
            "fixture-missing",
            "missing-run",
            "missing-target",
            "missing-attempt",
            paths=paths,
            max_response_bytes=4096,
        )


def test_capture_refuses_manifest_without_plan_provenance(
    tmp_path, monkeypatch
) -> None:
    paths, run_id, row = _make_run(tmp_path, lazy=False)
    _execute_run(
        paths,
        run_id,
        row,
        {row["target_url"]: b"<html>filing</html>"},
        monkeypatch,
    )
    create_fixture("fixture-invalid-manifest", paths=paths)
    state = get_target_state(paths.run_state_path(run_id), "target-1")
    assert state is not None and state.last_attempt_id is not None
    manifest_path = paths.run_manifest_path(run_id)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("run_digest")
    manifest.pop("target_plan_id")
    manifest["run_digest"] = canonical_hash(manifest)
    manifest_path.write_text(canonical_json(manifest), encoding="utf-8")

    with pytest.raises(FixtureOperationError, match="target-plan provenance"):
        capture_fixture_case(
            "fixture-invalid-manifest",
            run_id,
            "target-1",
            state.last_attempt_id,
            paths=paths,
            max_response_bytes=4096,
        )


@pytest.mark.parametrize("tamper", ("symlink", "digest"))
def test_capture_refuses_tampered_staged_bodies(tmp_path, monkeypatch, tamper) -> None:
    paths, run_id, row = _make_run(tmp_path, lazy=False)
    body = b"<html>untampered filing</html>"
    _execute_run(paths, run_id, row, {row["target_url"]: body}, monkeypatch)
    create_fixture(f"fixture-{tamper}", paths=paths)
    state = get_target_state(paths.run_state_path(run_id), "target-1")
    assert state is not None and state.last_attempt_id is not None
    relative = state.source_body_relative_path
    assert relative is not None
    staged = paths.run_dir(run_id) / relative
    staged.unlink()
    if tamper == "symlink":
        outside = tmp_path / "outside.bin"
        outside.write_bytes(body)
        staged.symlink_to(outside)
        message = "symlink"
    else:
        staged.write_bytes(b"X" * len(body))
        message = "response_sha256 does not match"

    with pytest.raises(FixtureOperationError, match=message):
        capture_fixture_case(
            f"fixture-{tamper}",
            run_id,
            "target-1",
            state.last_attempt_id,
            paths=paths,
            max_response_bytes=4096,
        )


def test_capture_enforces_response_size_limit_before_commit(
    tmp_path, monkeypatch
) -> None:
    paths, run_id, row = _make_run(tmp_path, lazy=False)
    body = b"<html>bounded capture</html>"
    _execute_run(paths, run_id, row, {row["target_url"]: body}, monkeypatch)
    create_fixture("fixture-limited", paths=paths)
    state = get_target_state(paths.run_state_path(run_id), "target-1")
    assert state is not None and state.last_attempt_id is not None

    with pytest.raises(FixtureOperationError, match="exceeds max_response_bytes"):
        capture_fixture_case(
            "fixture-limited",
            run_id,
            "target-1",
            state.last_attempt_id,
            paths=paths,
            max_response_bytes=len(body) - 1,
        )
    assert list(list_fixture_cases(paths, fixture_id="fixture-limited")) == []


def test_replay_reextracts_and_verifies_a_bundle_case(tmp_path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    initialize_fixture(paths, "fixture-bundle")
    bundle = (
        b"<DOCUMENT><SEQUENCE>2<FILENAME>report.htm<TYPE>10-K<TEXT>selected body"
        b"</TEXT></DOCUMENT>"
    )
    selected_body = b"selected body"
    source_digest = hashlib.sha256(bundle).hexdigest()
    selected_digest = hashlib.sha256(selected_body).hexdigest()
    capture = {
        "capture_id": "capture-bundle",
        "run_id": "run-bundle",
        "target_plan_id": "plan-bundle",
        "target_plan_digest": "a" * 64,
        "target_plan_schema_version": "1",
        "inventory_snapshot_id": None,
        "inventory_snapshot_digest": None,
        "captured_at_utc": "2025-01-01T00:00:00Z",
    }
    case = {
        "target_id": "target-bundle",
        "attempt_id": "attempt-bundle",
        "accession": "0000000001-24-000001",
        "form": "10-K",
        "request_id": "request-bundle",
        "target_role": "primary",
        "target_type": "primary",
        "optional": 0,
        "catalog_direct_selection": "submitted_primary",
        "source_origin": "catalog_direct",
        "target_status": "matched",
        "retrieval_mode": "bundle_sequence",
        "target_url": "https://www.sec.gov/submission.txt",
        "final_url": "https://www.sec.gov/submission.txt",
        "sequence": 2,
        "acquisition_status": "acquired",
        "error_code": None,
        "response_sha256": source_digest,
        "index_response_sha256": None,
        "selected_response_sha256": None,
        "resolution_schema_version": None,
        "screen_kind": "none",
        "screen_result": "not_run",
        "evaluator_version": None,
        "index_parser_version": None,
        "matching_entry_ids_json": None,
        "selected_sequence": None,
        "selected_retrieval_mode": None,
        "selected_url": None,
        "source_byte_size": len(bundle),
        "selected_sha256": selected_digest,
        "selected_byte_size": len(selected_body),
        "selected_filename": "report.htm",
        "content_type": None,
        "content_encoding": None,
    }
    append_fixture_case(
        paths,
        "fixture-bundle",
        capture,
        case,
        io.BytesIO(bundle),
        max_response_bytes=len(bundle),
    )
    output = tmp_path / "bundle-selected.htm"

    replay = replay_fixture_case(
        "fixture-bundle",
        "capture-bundle",
        "target-bundle",
        output,
        paths=paths,
    )

    assert replay.output_path == output
    assert replay.response_sha256 == source_digest
    assert output.read_bytes() == selected_body


def test_fixture_cli_completes_offline_retained_lazy_evidence_flow(
    tmp_path, monkeypatch, capsys
) -> None:
    paths, run_id, row = _make_run(tmp_path, lazy=True)
    selected_url = _INDEX_URL.rsplit("/", 1)[0] + "/report.htm"
    body = b"<html>offline retained lazy fixture cli</html>"
    _execute_run(
        paths,
        run_id,
        row,
        {
            row["target_url"]: b"<html>initial catalog response</html>",
            _INDEX_URL: _INDEX,
            selected_url: body,
        },
        monkeypatch,
        retain_response_evidence=True,
    )
    state = get_target_state(paths.run_state_path(run_id), "target-1")
    assert state is not None and state.last_attempt_id is not None
    attempt_id = _initial_attempt_id(paths, run_id)
    artifacts = str(paths.artifacts_root)

    assert (
        cli.main(
            [
                "fixture",
                "create",
                "--fixture-id",
                "fixture-cli",
                "--artifacts",
                artifacts,
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        cli.main(
            [
                "fixture",
                "capture",
                "--fixture-id",
                "fixture-cli",
                "--run-id",
                run_id,
                "--target-id",
                "target-1",
                "--attempt-id",
                attempt_id,
                "--max-response-bytes",
                "4096",
                "--artifacts",
                artifacts,
                "--json",
            ]
        )
        == 0
    )
    capture_result = json.loads(capsys.readouterr().out)
    capture_id = capture_result["capture_id"]
    output = tmp_path / "cli-replayed.html"

    assert (
        cli.main(
            [
                "fixture",
                "list",
                "--fixture-id",
                "fixture-cli",
                "--artifacts",
                artifacts,
                "--json",
            ]
        )
        == 0
    )
    listed = json.loads(capsys.readouterr().out)
    assert listed["cases"][0]["capture_id"] == capture_id
    case = listed["cases"][0]
    assert case["attempt_id"] == attempt_id
    assert case["response_sha256"] != case["selected_sha256"]
    assert case["index_response_sha256"] == hashlib.sha256(_INDEX).hexdigest()
    assert case["selected_response_sha256"] == hashlib.sha256(body).hexdigest()

    def unexpected(*_args, **_kwargs):
        raise AssertionError("fixture replay must not start acquisition")

    monkeypatch.setattr(run_command, "_LazySecTransport", unexpected)
    monkeypatch.setattr(run_command, "execute_acquisition_run", unexpected)
    assert (
        cli.main(
            [
                "fixture",
                "replay",
                "--fixture-id",
                "fixture-cli",
                "--capture-id",
                capture_id,
                "--target-id",
                "target-1",
                "--output",
                str(output),
                "--artifacts",
                artifacts,
                "--json",
            ]
        )
        == 0
    )
    replay_result = json.loads(capsys.readouterr().out)
    assert replay_result["status"] == "replayed"
    assert output.read_bytes() == body


def test_capture_refuses_older_document_body_attempt_after_retry(
    tmp_path, monkeypatch
) -> None:
    paths, run_id, row = _make_run(tmp_path, lazy=False)
    first_failure = StreamFailure("transport_error", True, None, "temporary failure")
    _execute_run(
        paths,
        run_id,
        row,
        {},
        monkeypatch,
        failures={row["target_url"]: first_failure},
        retain_response_evidence=True,
    )
    older_attempt_id = _initial_attempt_id(paths, run_id)
    _execute_run(
        paths,
        run_id,
        row,
        {row["target_url"]: b"<html>successful retry</html>"},
        monkeypatch,
        retry_failures=True,
        retain_response_evidence=True,
    )
    state = get_target_state(paths.run_state_path(run_id), "target-1")
    assert state is not None and state.last_attempt_id != older_attempt_id
    create_fixture("fixture-stale-attempt", paths=paths)

    with pytest.raises(FixtureOperationError) as exc_info:
        capture_fixture_case(
            "fixture-stale-attempt",
            run_id,
            "target-1",
            older_attempt_id,
            paths=paths,
            max_response_bytes=4096,
        )
    assert str(exc_info.value) == "attempt is not the latest target attempt"
