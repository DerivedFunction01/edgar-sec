"""The full registrant index as a cohort: split at the sink, collapse names, and
refuse a malformed line rather than silently shrinking the universe.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.paths import resolve_cohort_paths
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths
from edgar_sec.pipelines.metadata_sync.roster import RosterError
from edgar_sec.pipelines.metadata_sync.source_registry import (
    SOURCE_UNIVERSE_NAME,
    SOURCE_UNIVERSE_URL,
    SourceRegistryError,
    refresh_cik_lookup_universe,
    resolve_universe_snapshot,
)
from edgar_sec.pipelines.metadata_sync.universe import compile_universe_cohort
from tests.support import FakeSession, build_test_http, fixture_path

FIXTURE = fixture_path("cik_lookup_universe_mini.txt")


def _payload() -> bytes:
    return FIXTURE.read_bytes()


def _publish(session: FakeSession, tmp_path: Path, payload: bytes | None = None):
    """Publish a universe source snapshot from a scripted session."""
    session.register_bytes(
        SOURCE_UNIVERSE_URL, payload if payload is not None else _payload()
    )
    metadata = resolve_metadata_paths(tmp_path)
    manifest = refresh_cik_lookup_universe(
        metadata_paths=metadata, client=build_test_http(session)
    )
    return metadata, manifest


def test_the_fixture_has_no_trailing_newline() -> None:
    """The live payload's last line lacks one; a fixture that added one would differ."""
    assert not _payload().endswith(b"\n")


# ------------------------------------------------------------------ publication


def test_refresh_publishes_the_universe_snapshot(
    session: FakeSession, tmp_path: Path
) -> None:
    metadata, manifest = _publish(session, tmp_path)
    assert manifest["source"] == SOURCE_UNIVERSE_NAME
    assert manifest["source_url"] == SOURCE_UNIVERSE_URL
    assert manifest["distinct_cik_count"] == 12
    assert Path(manifest["raw_path"]).suffix == ".txt"
    assert Path(manifest["raw_path"]).read_bytes() == _payload()


def test_refresh_refuses_a_malformed_payload(
    session: FakeSession, tmp_path: Path
) -> None:
    bad = _payload() + b"NOT A LINE\n"
    with pytest.raises(SourceRegistryError, match="malformed"):
        _publish(session, tmp_path, payload=bad)


def test_resolve_returns_the_only_snapshot(
    session: FakeSession, tmp_path: Path
) -> None:
    metadata, manifest = _publish(session, tmp_path)
    assert resolve_universe_snapshot(metadata) == manifest["snapshot_id"]


def test_resolve_is_empty_without_a_snapshot(tmp_path: Path) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    assert resolve_universe_snapshot(metadata) == ""


def test_resolve_uses_the_active_catalog_pointer(
    session: FakeSession, tmp_path: Path
) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    _metadata, first = _publish(session, tmp_path)
    second_payload = _payload().replace(b"0001471283", b"0001471284", 1)
    _metadata, second = _publish(session, tmp_path, payload=second_payload)
    assert resolve_universe_snapshot(metadata) == second["snapshot_id"]
    assert second["snapshot_id"] != first["snapshot_id"]


# --------------------------------------------------------------- the cohort


def test_cohort_collapses_to_one_row_per_registrant(
    session: FakeSession, tmp_path: Path
) -> None:
    metadata, manifest = _publish(session, tmp_path)
    roster = compile_universe_cohort(
        metadata, source_snapshot_id=manifest["snapshot_id"]
    )
    assert roster.row_count == 12
    ciks = roster.range_ciks(0, roster.row_count)
    assert ciks == tuple(sorted(ciks))
    assert "0000000020" in ciks  # zero-padded from an unpadded source line
    assert "0002010293" in ciks


def test_a_repeated_registrant_keeps_the_first_name(
    session: FakeSession, tmp_path: Path
) -> None:
    """Three names share one CIK; the cohort keeps one, deterministically."""
    metadata, manifest = _publish(session, tmp_path)
    roster = compile_universe_cohort(
        metadata, source_snapshot_id=manifest["snapshot_id"]
    )
    names = dict(roster.iter_rows())
    assert names["0000798737"] == "AB MUNICIPAL INCOME FUND, INC."


def test_hostile_lines_survive_the_split(session: FakeSession, tmp_path: Path) -> None:
    """Quotes, embedded colons, and a trailing-colon name all round-trip."""
    metadata, manifest = _publish(session, tmp_path)
    roster = compile_universe_cohort(
        metadata, source_snapshot_id=manifest["snapshot_id"]
    )
    names = dict(roster.iter_rows())
    assert names["0001326293"] == 'COLUMBIA WEST CAPITAL, LLC ("CWC")'
    assert names["0001287865"] == "CONNECT 1:2:1 MOBILE INC"
    assert names["0001569340"] == "STUDIO :: J'HAN CO LLC"
    assert names["0001471283"] == "TOP-GOLD AG M.V.K"


def test_an_empty_name_is_kept(session: FakeSession, tmp_path: Path) -> None:
    """Two lines carry a CIK with no name; the registrant is still real."""
    metadata, manifest = _publish(session, tmp_path)
    roster = compile_universe_cohort(
        metadata, source_snapshot_id=manifest["snapshot_id"]
    )
    names = dict(roster.iter_rows())
    assert names["0001003197"] == ""
    assert names["0001036125"] == ""


def test_limit_selects_the_lowest_ciks(session: FakeSession, tmp_path: Path) -> None:
    metadata, manifest = _publish(session, tmp_path)
    full = compile_universe_cohort(metadata, source_snapshot_id=manifest["snapshot_id"])
    limited = compile_universe_cohort(
        metadata, source_snapshot_id=manifest["snapshot_id"], limit=3
    )
    assert limited.row_count == 3
    assert limited.range_ciks(0, 3) == full.range_ciks(0, 3)


def test_two_compiles_share_one_identity(session: FakeSession, tmp_path: Path) -> None:
    """Reordering or a lost ORDER BY would change the roster; it must not."""
    metadata, manifest = _publish(session, tmp_path)
    first = compile_universe_cohort(
        metadata, source_snapshot_id=manifest["snapshot_id"]
    )
    second = compile_universe_cohort(
        metadata, source_snapshot_id=manifest["snapshot_id"]
    )
    assert first.roster_id == second.roster_id


def test_a_recompiled_cohort_reuses_its_dataset(
    session: FakeSession, tmp_path: Path
) -> None:
    metadata, manifest = _publish(session, tmp_path)
    first = compile_universe_cohort(
        metadata, source_snapshot_id=manifest["snapshot_id"]
    )
    second = compile_universe_cohort(
        metadata, source_snapshot_id=manifest["snapshot_id"]
    )
    assert first.dataset == second.dataset


def test_a_different_limit_is_a_different_cohort(
    session: FakeSession, tmp_path: Path
) -> None:
    metadata, manifest = _publish(session, tmp_path)
    full = compile_universe_cohort(metadata, source_snapshot_id=manifest["snapshot_id"])
    limited = compile_universe_cohort(
        metadata, source_snapshot_id=manifest["snapshot_id"], limit=3
    )
    assert limited.roster_id != full.roster_id


def test_a_corrupted_shared_cohort_dataset_is_rejected(
    session: FakeSession, tmp_path: Path
) -> None:
    metadata, manifest = _publish(session, tmp_path)
    first = compile_universe_cohort(
        metadata, source_snapshot_id=manifest["snapshot_id"]
    )
    assert first.dataset is not None
    first.dataset.write_bytes(b"corrupt")
    with pytest.raises(RosterError, match="digest does not match"):
        compile_universe_cohort(metadata, source_snapshot_id=manifest["snapshot_id"])


def test_cohort_catalog_records_source_provenance(
    session: FakeSession, tmp_path: Path
) -> None:
    metadata, manifest = _publish(session, tmp_path)
    compile_universe_cohort(metadata, source_snapshot_id=manifest["snapshot_id"])
    paths = resolve_cohort_paths(metadata.artifacts_root)
    record = CohortCatalog(paths).resolve_cohort_identifier(manifest["cohort_id"])
    origin = json.loads(record.origin_json)
    assert origin["source_snapshot_id"] == manifest["snapshot_id"]
    assert origin["raw_sha256"] == manifest["raw_sha256"]


def test_unknown_snapshot_is_reported(session: FakeSession, tmp_path: Path) -> None:
    metadata, _manifest = _publish(session, tmp_path)
    with pytest.raises(FileNotFoundError):
        compile_universe_cohort(metadata, source_snapshot_id="does-not-exist")
