"""The full registrant index as a cohort: split at the sink, collapse names, and
refuse a malformed line rather than silently shrinking the universe.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths
from edgar_sec.pipelines.metadata_sync.source_registry import (
    SOURCE_UNIVERSE_NAME,
    SOURCE_UNIVERSE_URL,
    SourceRegistryError,
    load_source_snapshot,
    parse_cik_lookup_universe,
    refresh_cik_lookup_universe,
    resolve_universe_snapshot,
)
from edgar_sec.pipelines.metadata_sync.universe import (
    NAME_RULE,
    compile_universe_cohort,
)
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


# ------------------------------------------------------------------- the parser


def test_parse_counts_lines_registrants_and_repeats() -> None:
    _none, report = parse_cik_lookup_universe(
        _payload(), snapshot_id="snap", observed_at="2026-01-01T00:00:00Z"
    )
    assert report["line_count"] == 14
    assert report["distinct_cik_count"] == 12
    # Three names share one registrant, so two lines collapse away.
    assert report["collapsed_name_count"] == 2
    assert report["malformed_line_count"] == 0


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
    assert Path(manifest["raw_path"]).name == "raw.txt"

    loaded = load_source_snapshot(
        metadata.source_manifest_file(SOURCE_UNIVERSE_NAME, manifest["snapshot_id"])
    )
    assert loaded.raw_path.read_bytes() == _payload()


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


def test_resolve_picks_the_newest_of_two(session: FakeSession, tmp_path: Path) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    for snapshot_id, retrieved_at in (
        ("aaa", "2026-01-01T00:00:00Z"),
        ("bbb", "2026-02-01T00:00:00Z"),
    ):
        directory = metadata.source_dir(SOURCE_UNIVERSE_NAME, snapshot_id)
        directory.mkdir(parents=True)
        atomic_write_json(
            directory / "manifest.json",
            {"snapshot_id": snapshot_id, "retrieved_at": retrieved_at},
            canonical=False,
        )
    assert resolve_universe_snapshot(metadata) == "bbb"


def test_resolve_ignores_a_broken_manifest(tmp_path: Path) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    directory = metadata.source_dir(SOURCE_UNIVERSE_NAME, "broken")
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text("not json", encoding="utf-8")
    assert resolve_universe_snapshot(metadata) == ""


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


def test_a_corrupted_cohort_dataset_is_recompiled(
    session: FakeSession, tmp_path: Path
) -> None:
    metadata, manifest = _publish(session, tmp_path)
    first = compile_universe_cohort(
        metadata, source_snapshot_id=manifest["snapshot_id"]
    )
    assert first.dataset is not None
    first.dataset.write_bytes(b"corrupt")
    # Reuse must reject the tampered dataset and rebuild it, not trust it.
    rebuilt = compile_universe_cohort(
        metadata, source_snapshot_id=manifest["snapshot_id"]
    )
    assert rebuilt.roster_id == first.roster_id


def test_cohort_manifest_records_provenance(
    session: FakeSession, tmp_path: Path
) -> None:
    metadata, manifest = _publish(session, tmp_path)
    compile_universe_cohort(metadata, source_snapshot_id=manifest["snapshot_id"])
    cohort_manifest = metadata.compiled_cohort_manifest(
        f"universe-{manifest['snapshot_id']}"
    )
    recorded = json.loads(cohort_manifest.read_text(encoding="utf-8"))
    assert recorded["source_snapshot_id"] == manifest["snapshot_id"]
    assert recorded["raw_sha256"] == manifest["raw_sha256"]
    assert recorded["name_rule"] == NAME_RULE


def test_unknown_snapshot_is_reported(session: FakeSession, tmp_path: Path) -> None:
    metadata, _manifest = _publish(session, tmp_path)
    with pytest.raises(FileNotFoundError):
        compile_universe_cohort(metadata, source_snapshot_id="does-not-exist")
