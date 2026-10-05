"""Tests for run orchestration and the document-storage CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_sec.domain.document.acquisition import FetchResult, direct_acquisition
from edgar_sec.domain.document.models import DocumentLocator, FilingOccurrence
from edgar_sec.domain.identity import Cik
from edgar_sec.foundation.runtime.paths import ProjectPaths
from edgar_sec.pipelines.document_storage import cli
from edgar_sec.pipelines.document_storage.fixture_operator import list_fixtures
from edgar_sec.pipelines.document_storage.fixture_store import FixtureStore
from edgar_sec.pipelines.document_storage.operator import (
    OperatorError,
    make_fetcher,
    new_run_id,
    run_document_storage,
)

ACCESSION = "0001234567-11-000001"

BODY = """\
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION

FORM 10-K

ACME INDUSTRIAL WIDGETS, INC.
(Exact name of registrant as specified in its charter)

Delaware
(State or other jurisdiction of incorporation)

Commission File Number: 001-14103
(Exact name of registrant as specified in its charter)

PART I

ITEM 1. Business

The Company was founded in 1994 and is a leading provider of industrial \
widgets. It operates three manufacturing facilities and employs \
approximately 4,200 people worldwide.

SIGNATURES

/s/ Jane Q. Registrant
"""


@pytest.fixture
def paths(tmp_path: Path) -> ProjectPaths:
    return ProjectPaths(
        repo_root=tmp_path,
        artifacts_root=tmp_path / ".artifacts",
        uploads_root=tmp_path / "uploads",
    )


def _locator(
    document_path: str = "acme-10k.htm", form: str = "10-K"
) -> DocumentLocator:
    return DocumentLocator.from_parts(
        ACCESSION,
        document_path,
        archive_url=f"https://www.sec.gov/x/{document_path}",
        form=form,
        source_cik="1234567",
    )


def _occurrence(locator: DocumentLocator) -> FilingOccurrence:
    return FilingOccurrence(
        occurrence_id="occ-1",
        source_cik=Cik.from_raw("1234567"),
        accession=locator.accession,
        document_path=locator.document_path,
        form="10-K",
        filing_date="2012-02-15",
        report_date=None,
        doc_id=locator.document_locator_key,
    )


class DictFetcher:
    def __init__(self, responses: dict[str, bytes]) -> None:
        self.responses = responses
        self.calls = 0

    def fetch(self, locator: DocumentLocator) -> FetchResult:
        self.calls += 1
        payload = self.responses.get(locator.document_path)
        if payload is None:
            return FetchResult(locator, "missing")
        return FetchResult(locator, "ok", acquired=direct_acquisition(locator, payload))


def _seed_fixture(
    paths: ProjectPaths, fixture_id: str, locators, payload: bytes
) -> None:
    db_path = paths.fixture_db_path(fixture_id)
    with FixtureStore(db_path) as store:
        store.put_many(
            [(locator.document_locator_key, payload) for locator in locators]
        )


# --- run identity ---------------------------------------------------------


def test_new_run_id_is_unique_and_prefixed() -> None:
    first = new_run_id("smoke")
    second = new_run_id("smoke")
    assert first.startswith("smoke-")
    assert first != second


# --- fetcher resolution ---------------------------------------------------


def test_fixture_mode_requires_a_fixture_id(paths: ProjectPaths) -> None:
    with pytest.raises(OperatorError, match="requires a fixture id"):
        make_fetcher("fixture", paths)


def test_fixture_mode_requires_the_database_to_exist(paths: ProjectPaths) -> None:
    with pytest.raises(OperatorError, match="not found"):
        make_fetcher("fixture", paths, fixture_id="absent")


def test_fixture_mode_builds_a_working_fetcher(paths: ProjectPaths) -> None:
    locator = _locator()
    _seed_fixture(paths, "fix-1", [locator], BODY.encode())
    fetcher = make_fetcher("fixture", paths, fixture_id="fix-1")
    assert fetcher.fetch(locator).ok is True


def test_live_mode_without_a_client_is_rejected(paths: ProjectPaths) -> None:
    with pytest.raises(ValueError, match="http_client"):
        make_fetcher("live", paths)


# --- the run --------------------------------------------------------------


def _run(paths: ProjectPaths, **overrides):
    locator = _locator()
    kwargs = {
        "paths": paths,
        "run_id": "run-1",
        "chunk_ids": ["c1"],
        "locators_by_chunk": {"c1": [locator]},
        "occurrences_by_chunk": {"c1": [_occurrence(locator)]},
        "fetcher": DictFetcher({"acme-10k.htm": BODY.encode()}),
        "workers": 1,
    }
    kwargs.update(overrides)
    return run_document_storage(**kwargs)


def test_run_publishes_a_snapshot(paths: ProjectPaths) -> None:
    report = _run(paths)
    assert report.run_id == "run-1"
    assert report.snapshot_id
    assert report.artifact_path.is_file()
    assert report.merge.snapshot.row_count == 1
    assert report.total_documents == 1
    assert report.failed_documents == 0
    assert report.ok is True


def test_run_requires_a_chunk(paths: ProjectPaths) -> None:
    with pytest.raises(OperatorError, match="at least one chunk"):
        _run(paths, chunk_ids=[])


def test_run_refuses_to_publish_when_every_chunk_fails(paths: ProjectPaths) -> None:
    with pytest.raises(OperatorError, match="every chunk failed"):
        _run(paths, fetcher=DictFetcher({}))


def test_run_publishes_when_some_documents_are_missing(paths: ProjectPaths) -> None:
    good = _locator("good.htm")
    bad = _locator("bad.htm")
    report = _run(
        paths,
        locators_by_chunk={"c1": [good, bad]},
        occurrences_by_chunk={"c1": [_occurrence(good), _occurrence(bad)]},
        fetcher=DictFetcher({"good.htm": BODY.encode()}),
    )
    assert report.failed_documents == 1
    assert report.ok is False
    assert report.artifact_path.is_file()
    assert report.merge.snapshot.row_count == 2


def test_run_records_progress_stages(paths: ProjectPaths) -> None:
    seen: list[str] = []
    _run(paths, progress=lambda event: seen.append(event["stage"]))
    assert seen == ["chunks", "delegation", "publish"]


def test_run_report_serializes(paths: ProjectPaths) -> None:
    payload = _run(paths).to_dict()
    assert payload["run_id"] == "run-1"
    assert payload["total_documents"] == 1
    assert payload["ok"] is True
    assert json.dumps(payload)


def test_interrupted_run_resumes_and_reuses_its_chunks(paths: ProjectPaths) -> None:
    """The state a killed process leaves: chunks processed, nothing published."""
    from edgar_sec.pipelines.document_storage.worker import process_chunks

    locator = _locator()
    fetcher = DictFetcher({"acme-10k.htm": BODY.encode()})
    chunks_dir = paths.run_chunks_dir("run-interrupted")
    chunks_dir.mkdir(parents=True, exist_ok=True)
    process_chunks(
        ["c1"],
        {"c1": [locator]},
        {"c1": [_occurrence(locator)]},
        fetcher=fetcher,
        chunks_dir=chunks_dir,
        workers=1,
    )
    assert fetcher.calls == 1

    resumed_fetcher = DictFetcher({"acme-10k.htm": BODY.encode()})
    report = run_document_storage(
        paths=paths,
        run_id="run-interrupted",
        chunk_ids=["c1"],
        locators_by_chunk={"c1": [locator]},
        occurrences_by_chunk={"c1": [_occurrence(locator)]},
        fetcher=resumed_fetcher,
        workers=1,
    )
    assert resumed_fetcher.calls == 0
    assert report.artifact_path.is_file()
    assert report.merge.snapshot.row_count == 1


def test_republishing_the_same_run_is_refused(paths: ProjectPaths) -> None:
    """Snapshots are immutable, so a completed run cannot silently republish."""
    from edgar_sec.pipelines.document_storage.merger import MergeError

    _run(paths)
    with pytest.raises(MergeError, match="already exists"):
        _run(paths)


def test_run_from_a_fixture_end_to_end(paths: ProjectPaths) -> None:
    locator = _locator()
    _seed_fixture(paths, "fix-1", [locator], BODY.encode())
    report = run_document_storage(
        paths=paths,
        run_id="run-fixture",
        chunk_ids=["c1"],
        locators_by_chunk={"c1": [locator]},
        occurrences_by_chunk={"c1": [_occurrence(locator)]},
        mode="fixture",
        fixture_id="fix-1",
        workers=1,
    )
    assert report.ok is True
    assert report.artifact_path.is_file()


# --- CLI ------------------------------------------------------------------


def _write_plan(path: Path, locators, occurrences=()) -> Path:
    plan = {
        "chunks": [
            {
                "chunk_id": "c1",
                "locators": [
                    {
                        "accession": str(locator.accession),
                        "document_path": locator.document_path,
                        "archive_url": locator.archive_url,
                        "form": locator.form,
                        "source_cik": locator.source_cik,
                    }
                    for locator in locators
                ],
                "occurrences": [occurrence.to_row() for occurrence in occurrences],
            }
        ]
    }
    path.write_text(json.dumps(plan), encoding="utf-8")
    return path


def test_cli_status_with_nothing_published(
    paths: ProjectPaths,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "resolve_paths", lambda: paths)
    assert cli.main(["status"]) == 1
    assert "no snapshot is published" in capsys.readouterr().out


def test_cli_status_json(
    paths: ProjectPaths,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run(paths)
    monkeypatch.setattr(cli, "resolve_paths", lambda: paths)
    assert cli.main(["status", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["published"] is True
    assert payload["pointer"]["run_id"] == "run-1"


def test_cli_run_publishes(
    paths: ProjectPaths,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locator = _locator()
    _seed_fixture(paths, "fix-1", [locator], BODY.encode())
    plan = _write_plan(tmp_path / "plan.json", [locator])
    monkeypatch.setattr(cli, "resolve_paths", lambda: paths)
    code = cli.main(
        [
            "run",
            "--plan",
            str(plan),
            "--fixture",
            "fix-1",
            "--run-id",
            "cli-1",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["run_id"] == "cli-1"
    assert payload["ok"] is True
    assert Path(payload["artifact_path"]).is_file()


def test_cli_run_human_output(
    paths: ProjectPaths,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locator = _locator()
    _seed_fixture(paths, "fix-1", [locator], BODY.encode())
    plan = _write_plan(tmp_path / "plan.json", [locator])
    monkeypatch.setattr(cli, "resolve_paths", lambda: paths)
    assert cli.main(["run", "--plan", str(plan), "--fixture", "fix-1"]) == 0
    out = capsys.readouterr().out
    assert "snapshot" in out
    assert "rows" in out


def test_cli_run_respects_the_limit(
    paths: ProjectPaths,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locators = [_locator(f"d{i}.htm") for i in range(3)]
    _seed_fixture(paths, "fix-1", locators, BODY.encode())
    plan = _write_plan(tmp_path / "plan.json", locators)
    monkeypatch.setattr(cli, "resolve_paths", lambda: paths)
    assert (
        cli.main(["run", "--plan", str(plan), "--fixture", "fix-1", "--limit", "1"])
        == 0
    )


def test_cli_missing_plan_is_reported(
    paths: ProjectPaths,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "resolve_paths", lambda: paths)
    assert cli.main(["run", "--plan", "/absent.json", "--fixture", "fix-1"]) == 1
    assert "plan not found" in capsys.readouterr().err


def test_cli_empty_plan_is_reported(
    paths: ProjectPaths,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"chunks": []}), encoding="utf-8")
    monkeypatch.setattr(cli, "resolve_paths", lambda: paths)
    assert cli.main(["run", "--plan", str(plan), "--fixture", "fix-1"]) == 1
    assert "no chunks" in capsys.readouterr().err


def test_cli_missing_fixture_is_reported(
    paths: ProjectPaths,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_plan(tmp_path / "plan.json", [_locator()])
    monkeypatch.setattr(cli, "resolve_paths", lambda: paths)
    assert cli.main(["run", "--plan", str(plan), "--fixture", "absent"]) == 1
    assert "not found" in capsys.readouterr().err


def _review_run(root: Path, documents: dict[str, str]) -> Path:
    """Write a minimal review run on disk, for the compare command."""
    from edgar_sec.pipelines.document_storage.review_artifacts import (
        REVIEW_MANIFEST_NAME,
    )

    run = root
    (run / "cases").mkdir(parents=True, exist_ok=True)
    entries = []
    for document_id, text in documents.items():
        case_dir = run / "cases" / document_id
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / f"{document_id}.txt").write_text(text, encoding="utf-8")
        entries.append(
            {
                "document_id": document_id,
                "document_path": f"{document_id}.htm",
                "fixture_id": "fix-cli",
                "source_sha256": "a" * 64,
                "current_output_sha256": "b" * 64,
            }
        )
    (run / REVIEW_MANIFEST_NAME).write_text(
        "".join(json.dumps(entry, sort_keys=True) + "\n" for entry in entries),
        encoding="utf-8",
    )
    return run


def test_cli_review_requires_two_runs(
    paths: ProjectPaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A comparison needs both sides named; there is no implicit "latest"."""
    monkeypatch.setattr(cli, "resolve_paths", lambda: paths)
    with pytest.raises(SystemExit):
        cli.main(["review"])


def test_cli_review_reports_differences_and_exits_non_zero(
    paths: ProjectPaths,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _review_run(tmp_path / "run-a", {"doc-a": "one\n"})
    new = _review_run(tmp_path / "run-b", {"doc-a": "two\n"})
    output = tmp_path / "diff"
    monkeypatch.setattr(cli, "resolve_paths", lambda: paths)
    assert (
        cli.main(
            ["review", "--base", str(base), "--new", str(new), "--output", str(output)]
        )
        == 1
    )
    assert "changed" in capsys.readouterr().out
    assert (output / "summary.txt").is_file()


def test_cli_review_exits_zero_when_nothing_moved(
    paths: ProjectPaths,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _review_run(tmp_path / "run-a", {"doc-a": "same\n"})
    new = _review_run(tmp_path / "run-b", {"doc-a": "same\n"})
    monkeypatch.setattr(cli, "resolve_paths", lambda: paths)
    assert (
        cli.main(
            [
                "review",
                "--base",
                str(base),
                "--new",
                str(new),
                "--output",
                str(tmp_path / "diff"),
            ]
        )
        == 0
    )
    assert "no differences" in capsys.readouterr().out


def test_cli_review_artifacts_rejects_a_non_positive_limit(
    paths: ProjectPaths,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "resolve_paths", lambda: paths)
    assert cli.main(["review-artifacts", "--fixture", "fix-1", "--limit", "0"]) == 2
    assert "--limit must be positive" in capsys.readouterr().err


def test_cli_requires_a_command() -> None:
    with pytest.raises(SystemExit):
        cli.main([])


def test_cli_fill_and_fixture_discovery(
    paths: ProjectPaths,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locator = _locator()
    plan = _write_plan(tmp_path / "plan.json", [locator])

    class Client:
        def get_bytes(self, url: str) -> bytes:
            assert url == locator.archive_url
            return BODY.encode()

    monkeypatch.setattr(
        "edgar_sec.pipelines.document_storage.fixture_operator._make_http_client",
        lambda: Client(),
    )
    monkeypatch.setattr(cli, "resolve_paths", lambda: paths)
    assert (
        cli.main(["fill", "--plan", str(plan), "--fixture", "fix-cli", "--json"]) == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["newly_written"] == 1
    assert list_fixtures(paths)[0].fixture_id == "fix-cli"

    assert cli.main(["fixtures"]) == 0
    assert "manifest=valid" in capsys.readouterr().out


def test_fixture_replay_precedence_follows_cli_order(paths: ProjectPaths) -> None:
    locator = _locator()
    _seed_fixture(paths, "first", [locator], b"first payload")
    _seed_fixture(paths, "second", [locator], b"second payload")
    fetcher = make_fetcher("fixture", paths, fixture_id=["first", "second"])
    assert fetcher.fetch(locator).acquired.selected_payload == b"first payload"
    fetcher.close()


def test_cli_rejects_an_unknown_command() -> None:
    with pytest.raises(SystemExit):
        cli.main(["teleport"])


# --- the pre-2005 candidate counts -----------------------------------------

_ERA_ACCESSION = "0000890923-01-000002"


def _era_locator(document_path: str, form: str = "10-K") -> DocumentLocator:
    """A locator from the inversion era, so the candidate window is reachable."""
    return DocumentLocator.from_parts(
        _ERA_ACCESSION,
        document_path,
        archive_url=f"https://www.sec.gov/x/{document_path}",
        form=form,
        source_cik="890923",
    )


def _era_occurrence(
    locator: DocumentLocator,
    filing_date: str = "2001-03-01",
    occurrence_id: str = "occ-1",
) -> FilingOccurrence:
    return FilingOccurrence(
        occurrence_id=occurrence_id,
        source_cik=Cik.from_raw("890923"),
        accession=locator.accession,
        document_path=locator.document_path,
        form="10-K",
        filing_date=filing_date,
        report_date=None,
        doc_id=locator.document_locator_key,
    )


def _era_run(paths: ProjectPaths, **overrides):
    """One chunk holding a statutory exhibit, a form-named file, and a ticker."""
    exhibit = _era_locator("ex21.txt")
    form_named = _era_locator("ex-10k.htm")
    locators = [exhibit, form_named]
    occurrences = [
        _era_occurrence(exhibit, "2001-03-01", "occ-1"),
        _era_occurrence(form_named, "2001-03-01", "occ-2"),
    ]
    kwargs = {
        "paths": paths,
        "run_id": "run-era",
        "chunk_ids": ["c1"],
        "locators_by_chunk": {"c1": locators},
        "occurrences_by_chunk": {"c1": occurrences},
        "fetcher": DictFetcher(
            {"ex21.txt": b"EXHIBIT BODY", "ex-10k.htm": BODY.encode()}
        ),
        "workers": 1,
    }
    kwargs.update(overrides)
    return run_document_storage(**kwargs)


def test_run_report_carries_the_candidate_counts(paths: ProjectPaths) -> None:
    payload = _era_run(paths).to_dict()
    assert payload["candidate_eligible_count"] == 2
    assert payload["bundle_candidate_count"] == 1


def test_candidate_counts_aggregate_across_chunks(paths: ProjectPaths) -> None:
    exhibit = _era_locator("ex21.txt")
    ticker = _era_locator("exxon10k.htm")
    report = _era_run(
        paths,
        run_id="run-two-chunks",
        chunk_ids=["c1", "c2"],
        locators_by_chunk={"c1": [exhibit], "c2": [ticker]},
        occurrences_by_chunk={
            "c1": [_era_occurrence(exhibit, "2001-03-01", "occ-1")],
            "c2": [_era_occurrence(ticker, "2001-03-01", "occ-2")],
        },
    )
    assert report.candidate_eligible_count == 2
    assert report.bundle_candidate_count == 1


def test_candidate_counts_deduplicate_co_filer_occurrences(paths: ProjectPaths) -> None:
    exhibit = _era_locator("ex21.txt")
    occurrences = [
        _era_occurrence(exhibit, "2001-03-01", f"occ-{index}") for index in range(3)
    ]
    report = _era_run(
        paths,
        run_id="run-cofilers",
        locators_by_chunk={"c1": [exhibit]},
        occurrences_by_chunk={"c1": occurrences},
    )
    assert report.candidate_eligible_count == 1
    assert report.bundle_candidate_count == 1
    assert report.merge.snapshot.row_count == 3


def test_candidate_counts_cover_a_chunk_skipped_by_resume(paths: ProjectPaths) -> None:
    """A resumed chunk contributes its plan's candidates, not zero."""
    from edgar_sec.pipelines.document_storage.worker import process_chunks

    exhibit = _era_locator("ex21.txt")
    ticker = _era_locator("exxon10k.htm")
    chunks_dir = paths.run_chunks_dir("run-resume-candidates")
    chunks_dir.mkdir(parents=True, exist_ok=True)
    process_chunks(
        ["c1"],
        {"c1": [exhibit]},
        {"c1": [_era_occurrence(exhibit, "2001-03-01", "occ-1")]},
        fetcher=DictFetcher({"ex21.txt": b"EXHIBIT BODY"}),
        chunks_dir=chunks_dir,
        workers=1,
    )

    report = _era_run(
        paths,
        run_id="run-resume-candidates",
        chunk_ids=["c1", "c2"],
        locators_by_chunk={"c1": [exhibit], "c2": [ticker]},
        occurrences_by_chunk={
            "c1": [_era_occurrence(exhibit, "2001-03-01", "occ-1")],
            "c2": [_era_occurrence(ticker, "2001-03-01", "occ-2")],
        },
        fetcher=DictFetcher({}),
    )
    skipped = next(chunk for chunk in report.chunks if chunk.chunk_id == "c1")
    assert skipped.worker_id == "skipped"
    assert skipped.bundle_candidate_count == 1
    assert report.candidate_eligible_count == 2
    assert report.bundle_candidate_count == 1


def test_candidate_counts_are_not_persisted_in_the_snapshot(
    paths: ProjectPaths,
) -> None:
    report = _era_run(paths, run_id="run-no-persist")
    manifest = json.loads(
        (report.merge.snapshot.artifact_path.parent / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert "candidate_eligible_count" not in manifest
    assert "bundle_candidate_count" not in manifest


def test_cli_run_json_reports_candidate_counts(
    paths: ProjectPaths,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exhibit = _era_locator("ex21.txt")
    _seed_fixture(paths, "fix-era", [exhibit], b"EXHIBIT BODY")
    plan = _write_plan(tmp_path / "plan.json", [exhibit], [_era_occurrence(exhibit)])
    monkeypatch.setattr(cli, "resolve_paths", lambda: paths)
    assert cli.main(["run", "--plan", str(plan), "--fixture", "fix-era", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["candidate_eligible_count"] == 1
    assert payload["bundle_candidate_count"] == 1


def test_cli_run_human_output_reports_candidate_counts(
    paths: ProjectPaths,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exhibit = _era_locator("ex21.txt")
    _seed_fixture(paths, "fix-era-text", [exhibit], b"EXHIBIT BODY")
    plan = _write_plan(tmp_path / "plan.json", [exhibit], [_era_occurrence(exhibit)])
    monkeypatch.setattr(cli, "resolve_paths", lambda: paths)
    assert cli.main(["run", "--plan", str(plan), "--fixture", "fix-era-text"]) == 0
    out = capsys.readouterr().out
    assert "eligible      1" in out
    assert "candidates    1" in out


def test_root_launcher_registers_the_documents_pipeline() -> None:
    runpy_source = Path("run.py").read_text(encoding="utf-8")
    assert "document_storage" in runpy_source
    import run as launcher

    assert any(entry.id == "documents" for entry in launcher.ENTRIES)
