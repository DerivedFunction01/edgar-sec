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
def paths(tmp_path: Path) -> ProjectPaths:
    return ProjectPaths(
        repo_root=tmp_path,
        artifacts_root=tmp_path / ".artifacts",
        uploads_root=tmp_path / "uploads",
    )


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
