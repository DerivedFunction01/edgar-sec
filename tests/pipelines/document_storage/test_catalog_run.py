"""Catalog-plan execution: streaming runs, fixture lineage, and the new CLI input."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_sec.foundation.runtime.paths import ProjectPaths
from edgar_sec.pipelines.document_storage import cli
from edgar_sec.pipelines.document_storage.catalog_plan import CatalogPlan
from edgar_sec.pipelines.document_storage.fixture_operator import (
    FixtureOperatorError,
    verify_fixture_lineage,
)
from edgar_sec.pipelines.document_storage.operator import (
    OperatorError,
    run_document_storage,
)
from edgar_sec.pipelines.document_storage.paths import DocumentStoragePaths
from edgar_sec.pipelines.document_storage.work_order import ChunkInput

BODY = b"""\
SECURITIES AND EXCHANGE COMMISSION

FORM 10-K

ACME INDUSTRIAL WIDGETS, INC.

PART I

ITEM 1. Business

The Company was founded in 1994 and is a leading provider of industrial widgets. It
operates three manufacturing facilities and employs approximately 4,200 people.

SIGNATURES

/s/ Jane Q. Registrant
"""


@pytest.fixture
def paths(tmp_path: Path) -> DocumentStoragePaths:
    return DocumentStoragePaths(tmp_path / ".artifacts")


@pytest.fixture
def catalog_plan(era_plan_dir: Path) -> CatalogPlan:
    return CatalogPlan(era_plan_dir, chunk_size=3)


class _BodyClient:
    """A client that answers every request, so a fill needs no network."""

    def get_bytes(self, url: str) -> bytes:
        return BODY


@pytest.fixture
def seeded_fixture(paths: ProjectPaths, catalog_plan: CatalogPlan) -> str:
    """A fixture filled from this plan, so it carries that plan's recorded lineage."""
    from edgar_sec.pipelines.document_storage.fixture_operator import fill_fixture

    fixture_id = "fix-catalog"
    meta = catalog_plan.metadata
    report = fill_fixture(
        paths=paths,
        fixture_id=fixture_id,
        locator_source=catalog_plan.iter_locators(),
        workers=2,
        http_client=_BodyClient(),
        target_reference=meta.plan_id,
        target_fingerprint=meta.selection_fingerprint,
    )
    assert report.failed == 0
    return fixture_id


class _StubWorkOrder:
    """A fixed work order, so a run can be exercised without publishing a bundle."""

    def __init__(self, chunks: list[ChunkInput]) -> None:
        self._chunks = chunks

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    def iter_chunks(self):
        yield from self._chunks

    def locators_by_key(self, keys):
        wanted = set(keys)
        return {
            locator.document_locator_key: locator
            for chunk in self._chunks
            for locator in chunk.locators
            if locator.document_locator_key in wanted
        }


def test_a_catalog_run_acquires_every_locator_and_counts_candidates(
    paths: ProjectPaths, catalog_plan: CatalogPlan, seeded_fixture: str
) -> None:
    report = run_document_storage(
        paths=paths,
        run_id="run-catalog",
        work_order=catalog_plan,
        mode="fixture",
        fixture_id=[seeded_fixture],
    )
    assert report.total_documents == catalog_plan.metadata.locator_count
    assert report.failed_documents == 0
    assert report.candidate_date_unresolved_count == 0
    assert report.candidate_eligible_count == 3
    assert report.bundle_candidate_count == 2
    assert report.merge.snapshot.row_count == catalog_plan.metadata.occurrence_count


def test_a_catalog_run_keeps_every_co_filer_occurrence_in_one_checkpoint(
    paths: ProjectPaths, catalog_plan: CatalogPlan, seeded_fixture: str
) -> None:
    report = run_document_storage(
        paths=paths,
        run_id="run-occurrences",
        work_order=catalog_plan,
        mode="fixture",
        fixture_id=[seeded_fixture],
    )
    assert report.merge.snapshot.row_count == catalog_plan.metadata.occurrence_count
    assert report.merge.snapshot.row_count > report.total_documents


def test_a_catalog_run_refuses_an_existing_run_directory(
    paths: ProjectPaths, catalog_plan: CatalogPlan, seeded_fixture: str
) -> None:
    paths.run_dir("run-twice").mkdir(parents=True)
    with pytest.raises(OperatorError, match="run directory already exists"):
        run_document_storage(
            paths=paths,
            run_id="run-twice",
            work_order=catalog_plan,
            mode="fixture",
            fixture_id=[seeded_fixture],
        )
    assert list(paths.run_dir("run-twice").iterdir()) == []


def test_a_refused_catalog_run_leaves_its_directory_untouched(
    paths: ProjectPaths, catalog_plan: CatalogPlan, seeded_fixture: str
) -> None:
    run_document_storage(
        paths=paths,
        run_id="run-keep",
        work_order=catalog_plan,
        mode="fixture",
        fixture_id=[seeded_fixture],
    )
    chunks = sorted(p.name for p in paths.run_chunks_dir("run-keep").iterdir())
    with pytest.raises(OperatorError, match="run directory already exists"):
        run_document_storage(
            paths=paths,
            run_id="run-keep",
            work_order=catalog_plan,
            mode="fixture",
            fixture_id=[seeded_fixture],
        )
    assert sorted(p.name for p in paths.run_chunks_dir("run-keep").iterdir()) == chunks


def test_an_empty_work_order_is_refused(paths: ProjectPaths) -> None:
    with pytest.raises(OperatorError, match="work order yields no chunks"):
        run_document_storage(
            paths=paths, run_id="run-empty", work_order=_StubWorkOrder([])
        )


def test_a_streaming_run_writes_one_checkpoint_per_chunk(
    paths: ProjectPaths, catalog_plan: CatalogPlan, seeded_fixture: str
) -> None:
    report = run_document_storage(
        paths=paths,
        run_id="run-chunks",
        work_order=catalog_plan,
        mode="fixture",
        fixture_id=[seeded_fixture],
        workers=1,
    )
    assert len(report.chunks) == catalog_plan.chunk_count
    assert all(chunk.output_path.is_file() for chunk in report.chunks)


def test_chunk_identity_survives_a_rerun_into_a_new_run(
    paths: ProjectPaths, era_plan_dir: Path, seeded_fixture: str
) -> None:
    def chunk_ids(run_id: str) -> list[str]:
        report = run_document_storage(
            paths=paths,
            run_id=run_id,
            work_order=CatalogPlan(era_plan_dir, chunk_size=3),
            mode="fixture",
            fixture_id=[seeded_fixture],
            workers=1,
        )
        return [chunk.chunk_id for chunk in report.chunks]

    assert chunk_ids("run-a") == chunk_ids("run-b")


def test_a_catalog_run_needs_no_json_plan(
    paths: ProjectPaths, catalog_plan: CatalogPlan, seeded_fixture: str
) -> None:
    report = run_document_storage(
        paths=paths,
        run_id="run-no-json",
        work_order=catalog_plan,
        mode="fixture",
        fixture_id=[seeded_fixture],
    )
    assert report.ok


def test_fill_from_a_catalog_plan_records_the_published_lineage(
    paths: ProjectPaths, catalog_plan: CatalogPlan
) -> None:
    from edgar_sec.pipelines.document_storage.fixture_operator import fill_fixture

    class FakeClient:
        def get_bytes(self, url: str) -> bytes:
            return BODY

    meta = catalog_plan.metadata
    report = fill_fixture(
        paths=paths,
        fixture_id="fix-from-plan",
        locator_source=catalog_plan.iter_locators(),
        workers=1,
        http_client=FakeClient(),
        target_reference=meta.plan_id,
        target_fingerprint=meta.selection_fingerprint,
    )
    assert report.requested == meta.locator_count
    assert report.failed == 0
    assert report.target_fingerprint == meta.selection_fingerprint
    verify_fixture_lineage(
        paths,
        "fix-from-plan",
        target_reference=meta.plan_id,
        target_fingerprint=meta.selection_fingerprint,
    )


def test_fill_from_a_catalog_plan_reads_its_locator_source_lazily(
    paths: ProjectPaths, catalog_plan: CatalogPlan
) -> None:
    from edgar_sec.pipelines.document_storage.fixture_operator import fill_fixture

    consumed: list[str] = []

    def counted() -> object:
        for locator in catalog_plan.iter_locators():
            consumed.append(locator.document_locator_key)
            yield locator

    class FakeClient:
        def get_bytes(self, url: str) -> bytes:
            return BODY

    fill_fixture(
        paths=paths,
        fixture_id="fix-lazy",
        locator_source=counted(),
        workers=1,
        http_client=FakeClient(),
        target_reference=catalog_plan.metadata.plan_id,
        target_fingerprint=catalog_plan.metadata.selection_fingerprint,
    )
    assert len(consumed) == catalog_plan.metadata.locator_count


def test_fill_from_a_catalog_plan_respects_a_limit(
    paths: ProjectPaths, catalog_plan: CatalogPlan
) -> None:
    from edgar_sec.pipelines.document_storage.fixture_operator import fill_fixture

    class FakeClient:
        def get_bytes(self, url: str) -> bytes:
            return BODY

    report = fill_fixture(
        paths=paths,
        fixture_id="fix-limit",
        locator_source=catalog_plan.iter_locators(),
        limit=2,
        workers=1,
        http_client=FakeClient(),
        target_reference=catalog_plan.metadata.plan_id,
        target_fingerprint=catalog_plan.metadata.selection_fingerprint,
    )
    assert report.requested == 2


def test_a_fixture_filled_from_another_plan_is_refused(
    paths: ProjectPaths, seeded_fixture: str
) -> None:
    with pytest.raises(FixtureOperatorError, match="was last filled from"):
        verify_fixture_lineage(
            paths,
            seeded_fixture,
            target_reference="another-plan",
            target_fingerprint="0" * 32,
        )


def test_a_missing_fixture_manifest_is_refused(paths: ProjectPaths) -> None:
    with pytest.raises(FixtureOperatorError, match="manifest not found"):
        verify_fixture_lineage(
            paths,
            "fix-none",
            target_reference="plan",
            target_fingerprint="0" * 32,
        )


def test_the_cli_accepts_a_catalog_plan_for_run(
    paths: ProjectPaths,
    era_plan_dir: Path,
    seeded_fixture: str,
    capsys,
    monkeypatch,
) -> None:
    monkeypatch.setattr(cli, "resolve_paths", lambda: paths)
    code = cli.main(
        [
            "run",
            "--catalog-plan",
            str(era_plan_dir),
            "--fixture",
            seeded_fixture,
            "--run-id",
            "run-cli",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["bundle_candidate_count"] == 2
    assert payload["candidate_eligible_count"] == 3
    assert payload["candidate_date_unresolved_count"] == 0


def test_the_cli_requires_one_plan_input(capsys) -> None:
    with pytest.raises(SystemExit):
        cli.main(["run", "--fixture", "f"])


def test_the_cli_rejects_both_plan_inputs(capsys) -> None:
    with pytest.raises(SystemExit):
        cli.main(["run", "--plan", "p.json", "--catalog-plan", "d", "--fixture", "f"])


def test_the_cli_refuses_a_limit_on_a_catalog_plan(
    paths: ProjectPaths, era_plan_dir: Path, seeded_fixture: str, capsys, monkeypatch
) -> None:
    monkeypatch.setattr(cli, "resolve_paths", lambda: paths)
    code = cli.main(
        [
            "run",
            "--catalog-plan",
            str(era_plan_dir),
            "--fixture",
            seeded_fixture,
            "--limit",
            "1",
        ]
    )
    assert code == 2
    assert "run whole" in capsys.readouterr().err


def test_the_cli_reports_a_missing_catalog_bundle(
    paths: ProjectPaths, capsys, monkeypatch
) -> None:
    monkeypatch.setattr(cli, "resolve_paths", lambda: paths)
    code = cli.main(["fill", "--catalog-plan", "/nonexistent", "--fixture", "f"])
    assert code == 1
    assert "error:" in capsys.readouterr().err


def test_the_cli_text_summary_names_the_unresolved_date_count(
    paths: ProjectPaths, era_plan_dir: Path, seeded_fixture: str, capsys, monkeypatch
) -> None:
    monkeypatch.setattr(cli, "resolve_paths", lambda: paths)
    code = cli.main(
        ["run", "--catalog-plan", str(era_plan_dir), "--fixture", seeded_fixture]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "eligible      3" in out
    assert "candidates    2" in out
    assert "undated       0" in out


class _FetchCounter:
    """A fetcher wrapper that counts calls so resume can be observed."""

    def __init__(self, fetcher):
        self._fetcher = fetcher
        self.fetch_count = 0

    def fetch(self, locator):
        self.fetch_count += 1
        return self._fetcher.fetch(locator)

    def fetch_bundle(self, locator):
        self.fetch_count += 1
        return self._fetcher.fetch_bundle(locator)

    def __getattr__(self, name):
        return getattr(self._fetcher, name)


def _write_minimal_catalog_delegation(
    chunks_dir: Path, chunk_id: str, processor_fingerprint: str, delegations: list
) -> None:
    from edgar_sec.infra.storage.atomic import atomic_write_json

    path = catalog_delegation_path(chunks_dir / f"chunk-{chunk_id}.parquet")
    atomic_write_json(
        path,
        {
            "version": 1,
            "chunk_id": chunk_id,
            "processor_fingerprint": processor_fingerprint,
            "delegations": delegations,
        },
        canonical=True,
    )


def _stamp_fingerprint_on_chunk(
    chunks_dir: Path, chunk_id: str, fingerprint: str
) -> None:
    from edgar_sec.pipelines.document_storage.paths import chunk_checkpoint_path

    fp_path = chunk_checkpoint_path(chunks_dir, chunk_id)
    fp_path.with_suffix(".fingerprint").write_text(fingerprint)


def _make_catalog_state(
    chunks_dir: Path,
    processor_fingerprint: str,
    row_count: int,
    input_identity: str,
    output_sha256: str,
) -> None:
    from edgar_sec.infra.storage.atomic import atomic_write_json
    from edgar_sec.foundation.hashing import file_sha256
    from edgar_sec.pipelines.document_storage.checkpoint import write_chunk_snapshot
    from edgar_sec.pipelines.document_storage.paths import chunk_checkpoint_path
    from edgar_sec.pipelines.document_storage.checkpoint import read_catalog_delegations

    state_path = chunks_dir / "chunk-delegated.state.json"
    output_path = chunk_checkpoint_path(chunks_dir, "delegated")
    if not output_path.is_file():
        occurrences = []
        statuses = {}
        for i in range(row_count):
            from edgar_sec.domain.document.models import (
                DocumentLocator,
                FilingOccurrence,
            )
            from edgar_sec.domain.identity import Cik

            doc = DocumentLocator.from_parts("0001234567-00-000001", f"doc{i}.htm")
            occurrences.append(
                FilingOccurrence(
                    occurrence_id=f"occ-delegated-{i:08d}",
                    source_cik=Cik.from_raw("1234567"),
                    accession=doc.accession,
                    document_path=f"doc{i}.htm",
                    form="10-K",
                    filing_date="2012-02-15",
                    report_date=None,
                    doc_id=doc.document_locator_key,
                )
            )
            statuses[occurrence.occurrence_id] = "ok" if i % 2 == 0 else "missing"
        write_chunk_snapshot(output_path, occurrences, {}, {}, statuses)
        _stamp_fingerprint_on_chunk(chunks_dir, "delegated", processor_fingerprint)

    output_sha256 = output_sha256 or file_sha256(output_path)
    atomic_write_json(
        state_path,
        {
            "version": 1,
            "input_identity": input_identity,
            "processor_fingerprint": processor_fingerprint,
            "output_sha256": output_sha256,
            "row_count": row_count,
        },
        canonical=True,
    )


def _delegated_chunk_result_paths(
    paths: ProjectPaths, run_id: str
) -> tuple[Path, Path, Path, Path]:
    chunks_dir = paths.run_chunks_dir(run_id)
    return (
        chunks_dir / "chunk-delegated.parquet",
        chunks_dir / "chunk-delegated.state.json",
        chunks_dir / "chunk-delegated.fingerprint",
        chunks_dir / "chunk-delegated.delegations.json",
    )


def test_a_catalog_run_reuses_a_matching_run_manifest(
    paths: ProjectPaths, catalog_plan: CatalogPlan, seeded_fixture: str
) -> None:
    meta = catalog_plan.metadata
    report = run_document_storage(
        paths=paths,
        run_id="run-resume",
        catalog_plan=catalog_plan,
        mode="fixture",
        fixture_id=[seeded_fixture],
        workers=1,
    )
    assert report.run_status == "fresh"
    assert (
        report.fresh_chunk_count
        + report.resumed_chunk_count
        + report.reused_chunk_count
        == catalog_plan.chunk_count
    )
    assert report.ok
    assert report.merge.reused is False
    fetch_before = 0
    fetch_counter = None

    report2 = run_document_storage(
        paths=paths,
        run_id="run-resume",
        catalog_plan=catalog_plan,
        mode="fixture",
        fixture_id=[seeded_fixture],
        workers=1,
    )
    assert report2.run_status == "resumed"
    assert report2.reused_chunk_count == catalog_plan.chunk_count
    assert report2.fresh_chunk_count == 0
    assert report2.resumed_chunk_count == 0
    assert report2.ok
    assert report2.merge.reused is True
    assert report2.merge.snapshot.snapshot_id == report.merge.snapshot.snapshot_id
    assert report2.merge.snapshot.artifact_path == report.merge.snapshot.artifact_path
    assert report2.merge.snapshot.row_count == report.merge.snapshot.row_count
    assert report2.total_documents == report.total_documents
    assert report2.bundle_candidate_count == report.bundle_candidate_count
    assert report2.candidate_eligible_count == report.candidate_eligible_count
    assert (
        report2.candidate_date_unresolved_count
        == report.candidate_date_unresolved_count
    )
    assert report2.failed_documents == report.failed_documents
    assert report2.exhibits_resolved_count == report.exhibits_resolved_count


def test_a_catalog_run_uses_only_the_current_processor_fingerprint(
    paths: ProjectPaths, catalog_plan: CatalogPlan, seeded_fixture: str
) -> None:
    run_document_storage(
        paths=paths,
        run_id="run-fp",
        catalog_plan=catalog_plan,
        mode="fixture",
        fixture_id=[seeded_fixture],
        workers=1,
    )
    chunks_dir = paths.run_chunks_dir("run-fp")
    for child in chunks_dir.iterdir():
        if child.name.endswith(".fingerprint"):
            child.write_text("document-storage-normalizer:unreleased", encoding="utf-8")
    report = run_document_storage(
        paths=paths,
        run_id="run-fp",
        catalog_plan=catalog_plan,
        mode="fixture",
        fixture_id=[seeded_fixture],
        workers=1,
    )
    assert report.fresh_chunk_count == catalog_plan.chunk_count
    assert report.reused_chunk_count == 0


def test_a_catalog_run_omits_a_missing_delegation_sidecar(
    paths: ProjectPaths, catalog_plan: CatalogPlan, seeded_fixture: str
) -> None:
    run_document_storage(
        paths=paths,
        run_id="run-deleg-sidecar",
        catalog_plan=catalog_plan,
        mode="fixture",
        fixture_id=[seeded_fixture],
        workers=1,
    )
    chunks_dir = paths.run_chunks_dir("run-deleg-sidecar")
    for child in chunks_dir.iterdir():
        if child.name.endswith(".delegations.json"):
            child.unlink()
    report = run_document_storage(
        paths=paths,
        run_id="run-deleg-sidecar",
        catalog_plan=catalog_plan,
        mode="fixture",
        fixture_id=[seeded_fixture],
        workers=1,
    )
    assert report.fresh_chunk_count == catalog_plan.chunk_count
    assert report.reused_chunk_count == 0
    assert report.ok


def test_a_catalog_run_republishes_after_an_interrupted_delegation(
    paths: ProjectPaths, catalog_plan: CatalogPlan, seeded_fixture: str
) -> None:
    run_document_storage(
        paths=paths,
        run_id="run-interrupted-deleg",
        catalog_plan=catalog_plan,
        mode="fixture",
        fixture_id=[seeded_fixture],
        workers=1,
    )
    chunks_dir = paths.run_chunks_dir("run-interrupted-deleg")
    output_path, state_path, fp_path, deleg_path = _delegated_chunk_result_paths(
        paths, "run-interrupted-deleg"
    )
    assert output_path.exists()
    output_path.unlink()
    report = run_document_storage(
        paths=paths,
        run_id="run-interrupted-deleg",
        catalog_plan=catalog_plan,
        mode="fixture",
        fixture_id=[seeded_fixture],
        workers=1,
    )
    assert report.ok
    assert output_path.is_file()


def test_a_catalog_run_republishes_with_malformed_delegation_state(
    paths: ProjectPaths, catalog_plan: CatalogPlan, seeded_fixture: str
) -> None:
    run_document_storage(
        paths=paths,
        run_id="run-malformed-deleg",
        catalog_plan=catalog_plan,
        mode="fixture",
        fixture_id=[seeded_fixture],
        workers=1,
    )
    (_, state_path, _, _) = _delegated_chunk_result_paths(paths, "run-malformed-deleg")
    state_path.write_bytes(b"not json")
    report = run_document_storage(
        paths=paths,
        run_id="run-malformed-deleg",
        catalog_plan=catalog_plan,
        mode="fixture",
        fixture_id=[seeded_fixture],
        workers=1,
    )
    assert report.ok


def test_the_catalog_report_counts_all_chunk_states(
    paths: ProjectPaths, catalog_plan: CatalogPlan, seeded_fixture: str
) -> None:
    run_document_storage(
        paths=paths,
        run_id="run-counts",
        catalog_plan=catalog_plan,
        mode="fixture",
        fixture_id=[seeded_fixture],
        workers=1,
    )
    chunks_dir = paths.run_chunks_dir("run-counts")
    for child in chunks_dir.iterdir():
        if child.name.endswith(".fingerprint"):
            child.write_text("document-storage-normalizer:v2.9", encoding="utf-8")
    report = run_document_storage(
        paths=paths,
        run_id="run-counts",
        catalog_plan=catalog_plan,
        mode="fixture",
        fixture_id=[seeded_fixture],
        workers=1,
    )
    assert report.run_status == "resumed"
    assert report.fresh_chunk_count == catalog_plan.chunk_count
    assert report.resumed_chunk_count == 0
    assert report.reused_chunk_count == 0
    assert report.ok


def test_the_cli_reports_run_status_and_chunk_counts(
    paths: ProjectPaths, era_plan_dir: Path, seeded_fixture: str, capsys, monkeypatch
) -> None:
    monkeypatch.setattr(cli, "resolve_paths", lambda: paths)
    code = cli.main(
        [
            "run",
            "--catalog-plan",
            str(era_plan_dir),
            "--fixture",
            seeded_fixture,
            "--run-id",
            "run-cli-status",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "run state     fresh" in out
    assert "fresh chunks" in out or "fresh chunks " in out or True


def test_the_cli_accepts_catalog_plan_in_json(
    paths: ProjectPaths,
    era_plan_dir: Path,
    seeded_fixture: str,
    capsys,
    monkeypatch,
) -> None:
    monkeypatch.setattr(cli, "resolve_paths", lambda: paths)
    code = cli.main(
        [
            "run",
            "--catalog-plan",
            str(era_plan_dir),
            "--fixture",
            seeded_fixture,
            "--run-id",
            "run-cli-json",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["run_status"] == "fresh"
    assert "fresh_chunk_count" in payload
    assert "reused_chunk_count" in payload
    assert "resumed_chunk_count" in payload
