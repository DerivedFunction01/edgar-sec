"""Copy-based distribution: a worker is handed a verifiable bundle and a chunk
list it cannot widen, and the coordinator refuses what it cannot prove.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from edgar_sec.domain.sec_urls import submissions_url
from edgar_sec.pipelines.metadata_sync import cli as cli_module
from edgar_sec.pipelines.metadata_sync.cli import main
from edgar_sec.pipelines.metadata_sync.sec_client import SubmissionsClient
from tests.support import FakeSession, build_test_http, fixture_path

MINI = ["0000001985", "0000001761", "0000000020", "0000037996"]


def _plan_argv(artifacts: Path, *extra: str) -> list[str]:
    return [
        "plan",
        "--input",
        str(fixture_path("cik_sec_mini.csv")),
        "--artifacts",
        str(artifacts),
        *extra,
    ]


def _seed_session_for(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    for cik in MINI:
        session.register(
            submissions_url(cik),
            {
                "name": f"CO {cik}",
                "cik": int(cik),
                "filings": {"recent": {}, "files": []},
            },
        )
    monkeypatch.setattr(
        cli_module,
        "_build_client",
        lambda: SubmissionsClient(http=build_test_http(session)),
    )


def _prepare(tmp_path: Path, capsys) -> str:
    assert main(_plan_argv(tmp_path, "--chunk-size", "1")) == 0
    return json.loads(capsys.readouterr().out)["plan_id"]


def test_export_writes_one_bundle_per_worker(tmp_path: Path, capsys) -> None:
    plan_id = _prepare(tmp_path, capsys)
    destination = tmp_path / "out"
    assert (
        main(
            [
                "export",
                "--plan-id",
                plan_id,
                "--artifacts",
                str(tmp_path),
                "--worker-count",
                "2",
                "--destination",
                str(destination),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["plan_id"] == plan_id
    assert {entry["worker_id"] for entry in payload["workers"]} == {
        "worker-00",
        "worker-01",
    }
    for entry in payload["workers"]:
        bundle = destination / entry["worker_id"]
        assert (bundle / "plan.json").is_file()
        assert (bundle / "roster" / "ciks.parquet").is_file()
        assert (bundle / "assignments" / f"{entry['assignment_id']}.parquet").is_file()
    for entry in payload["workers"]:
        manifest = json.loads(
            (destination / entry["worker_id"] / "plan.json").read_text(encoding="utf-8")
        )
        assert manifest["plan_id"] == plan_id


def test_every_worker_receives_a_byte_identical_bundle(tmp_path: Path, capsys) -> None:
    """Only the assignment differs, so a worker can verify what it was handed."""
    plan_id = _prepare(tmp_path, capsys)
    destination = tmp_path / "out"
    main(
        [
            "export",
            "--plan-id",
            plan_id,
            "--artifacts",
            str(tmp_path),
            "--worker-count",
            "2",
            "--destination",
            str(destination),
        ]
    )
    capsys.readouterr()
    digests = {
        (
            (destination / worker / "plan.json").read_bytes(),
            (destination / worker / "roster" / "ciks.parquet").read_bytes(),
        )
        for worker in ("worker-00", "worker-01")
    }
    assert len(digests) == 1


def test_worker_runs_its_assignment_and_emits_a_receipt(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_session_for(monkeypatch)
    plan_id = _prepare(tmp_path, capsys)
    destination = tmp_path / "out"
    main(
        [
            "export",
            "--plan-id",
            plan_id,
            "--artifacts",
            str(tmp_path),
            "--worker-count",
            "2",
            "--destination",
            str(destination),
        ]
    )
    capsys.readouterr()

    bundle = destination / "worker-00"
    assert main(["worker", "--bundle", str(bundle)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["worker_id"] == "worker-00"
    assert payload["chunks"] == [0, 2]
    receipt = json.loads((bundle / "receipt.json").read_text())
    assert receipt["plan_id"] == plan_id
    assert {entry["chunk_id"] for entry in receipt["chunks"]} == {0, 2}
    assert all(len(entry["file_sha256"]) == 64 for entry in receipt["chunks"])


def test_worker_refuses_a_bundle_carrying_several_assignments(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A machine must not silently claim work another machine was given."""
    _seed_session_for(monkeypatch)
    plan_id = _prepare(tmp_path, capsys)
    destination = tmp_path / "out"
    main(
        [
            "export",
            "--plan-id",
            plan_id,
            "--artifacts",
            str(tmp_path),
            "--worker-count",
            "2",
            "--destination",
            str(destination),
        ]
    )
    capsys.readouterr()
    combined = tmp_path / "combined"
    combined.mkdir()
    for name in ("plan.json", "roster", "assignments"):
        source = destination / "worker-00" / name
        target = combined / name
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    for worker in ("worker-00", "worker-01"):
        assignment = next((destination / worker / "assignments").glob("*.parquet"))
        shutil.copy2(assignment, combined / "assignments" / assignment.name)

    assert main(["worker", "--bundle", str(combined)]) == 1
    assert "name one with --worker" in capsys.readouterr().err

    assert main(["worker", "--bundle", str(combined), "--worker", "worker-01"]) == 0
    assert json.loads(capsys.readouterr().out)["worker_id"] == "worker-01"


def test_import_adopts_returned_chunks(tmp_path: Path, capsys, monkeypatch) -> None:
    _seed_session_for(monkeypatch)
    plan_id = _prepare(tmp_path, capsys)
    destination = tmp_path / "out"
    main(
        [
            "export",
            "--plan-id",
            plan_id,
            "--artifacts",
            str(tmp_path),
            "--worker-count",
            "2",
            "--destination",
            str(destination),
        ]
    )
    capsys.readouterr()
    for worker in ("worker-00", "worker-01"):
        main(["worker", "--bundle", str(destination / worker)])
        capsys.readouterr()

    assert (
        main(
            [
                "import",
                "--plan-id",
                plan_id,
                "--artifacts",
                str(tmp_path),
                "--source",
                str(destination / "worker-00"),
            ]
        )
        == 0
    )
    first = json.loads(capsys.readouterr().out)
    assert first["imported_chunks"] == [0, 2]

    assert (
        main(
            [
                "import",
                "--plan-id",
                plan_id,
                "--artifacts",
                str(tmp_path),
                "--source",
                str(destination / "worker-01"),
            ]
        )
        == 0
    )
    second = json.loads(capsys.readouterr().out)
    assert second["imported_chunks"] == [1, 3]

    assert main(["status", "--plan-id", plan_id, "--artifacts", str(tmp_path)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["mergeable"] is True


def test_import_is_idempotent_for_a_byte_identical_return(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    _seed_session_for(monkeypatch)
    plan_id = _prepare(tmp_path, capsys)
    destination = tmp_path / "out"
    main(
        [
            "export",
            "--plan-id",
            plan_id,
            "--artifacts",
            str(tmp_path),
            "--worker-count",
            "2",
            "--destination",
            str(destination),
        ]
    )
    capsys.readouterr()
    main(["worker", "--bundle", str(destination / "worker-00")])
    capsys.readouterr()

    source = str(destination / "worker-00")
    main(
        [
            "import",
            "--plan-id",
            plan_id,
            "--artifacts",
            str(tmp_path),
            "--source",
            source,
        ]
    )
    assert json.loads(capsys.readouterr().out)["imported_chunks"] == [0, 2]
    main(
        [
            "import",
            "--plan-id",
            plan_id,
            "--artifacts",
            str(tmp_path),
            "--source",
            source,
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported_chunks"] == []
    assert payload["already_present"] == [0, 2]


def test_import_rejects_a_tampered_chunk(tmp_path: Path, capsys, monkeypatch) -> None:
    _seed_session_for(monkeypatch)
    plan_id = _prepare(tmp_path, capsys)
    destination = tmp_path / "out"
    main(
        [
            "export",
            "--plan-id",
            plan_id,
            "--artifacts",
            str(tmp_path),
            "--worker-count",
            "2",
            "--destination",
            str(destination),
        ]
    )
    capsys.readouterr()
    main(["worker", "--bundle", str(destination / "worker-00")])
    capsys.readouterr()

    target = destination / "worker-00" / "chunks" / "chunk_0000.parquet"
    target.write_bytes(target.read_bytes() + b"tampered")
    assert (
        main(
            [
                "import",
                "--plan-id",
                plan_id,
                "--artifacts",
                str(tmp_path),
                "--source",
                str(destination / "worker-00"),
            ]
        )
        == 1
    )
    assert "digest does not match" in capsys.readouterr().err


def test_import_rejects_a_receipt_for_another_plan(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    _seed_session_for(monkeypatch)
    plan_id = _prepare(tmp_path, capsys)
    destination = tmp_path / "out"
    main(
        [
            "export",
            "--plan-id",
            plan_id,
            "--artifacts",
            str(tmp_path),
            "--worker-count",
            "2",
            "--destination",
            str(destination),
        ]
    )
    capsys.readouterr()
    main(["worker", "--bundle", str(destination / "worker-00")])
    capsys.readouterr()

    receipt_path = destination / "worker-00" / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["plan_id"] = "ffffffffffffffff"
    receipt_path.write_text(json.dumps(receipt))
    assert (
        main(
            [
                "import",
                "--plan-id",
                plan_id,
                "--artifacts",
                str(tmp_path),
                "--source",
                str(destination / "worker-00"),
            ]
        )
        == 1
    )
    assert "contents derive" in capsys.readouterr().err


def test_import_rejects_a_chunk_the_assignment_never_claimed(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """A receipt widened after the fact must not be able to import extra work."""
    _seed_session_for(monkeypatch)
    plan_id = _prepare(tmp_path, capsys)
    destination = tmp_path / "out"
    main(
        [
            "export",
            "--plan-id",
            plan_id,
            "--artifacts",
            str(tmp_path),
            "--worker-count",
            "2",
            "--destination",
            str(destination),
        ]
    )
    capsys.readouterr()
    main(["worker", "--bundle", str(destination / "worker-00")])
    capsys.readouterr()

    worker_dir = destination / "worker-00"
    shutil.copy2(
        tmp_path / "metadata" / "plans" / plan_id / "roster" / "ciks.parquet",
        worker_dir / "roster" / "ciks.parquet",
    )
    receipt_path = worker_dir / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["chunks"].append(
        {
            "chunk_id": 1,
            "relative_path": "chunks/chunk_0001.parquet",
            "row_count": 1,
            "file_sha256": "a" * 64,
        }
    )
    receipt_path.write_text(json.dumps(receipt))
    assert (
        main(
            [
                "import",
                "--plan-id",
                plan_id,
                "--artifacts",
                str(tmp_path),
                "--source",
                str(worker_dir),
            ]
        )
        == 1
    )
    assert "contents derive" in capsys.readouterr().err


def test_import_refuses_to_overwrite_a_different_chunk(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """Same schema, CIKs, and row count, differing only in content: undecidable."""
    import pyarrow.parquet as pq

    from edgar_sec.engine.submissions.builder import build_submission_table
    from edgar_sec.pipelines.metadata_sync.paths import resolve_run_paths

    _seed_session_for(monkeypatch)
    plan_id = _prepare(tmp_path, capsys)
    destination = tmp_path / "out"
    main(
        [
            "export",
            "--plan-id",
            plan_id,
            "--artifacts",
            str(tmp_path),
            "--worker-count",
            "2",
            "--destination",
            str(destination),
        ]
    )
    capsys.readouterr()
    main(["worker", "--bundle", str(destination / "worker-00")])
    capsys.readouterr()
    main(
        [
            "import",
            "--plan-id",
            plan_id,
            "--artifacts",
            str(tmp_path),
            "--source",
            str(destination / "worker-00"),
        ]
    )
    capsys.readouterr()

    local = resolve_run_paths(plan_id, tmp_path).chunk_file(0)
    rows = pq.read_table(local).to_pylist()
    for row in rows:
        row["fetched_at"] = "1999-01-01T00:00:00Z"
    pq.write_table(build_submission_table(rows), local)

    assert (
        main(
            [
                "import",
                "--plan-id",
                plan_id,
                "--artifacts",
                str(tmp_path),
                "--source",
                str(destination / "worker-00"),
            ]
        )
        == 1
    )
    assert "resolve the conflict" in capsys.readouterr().err
