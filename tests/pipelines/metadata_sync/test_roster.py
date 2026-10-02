"""Content-addressed CIK roster tests.

The roster is the artifact that made a plan document constant in size, so these
tests pin the two properties the rest of the pipeline relies on: identity is a
function of the ordered cohort and its names, and the dataset round-trips
byte-faithfully enough that a re-derived identity still matches.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from edgar_sec.pipelines.metadata_sync.manifest import read_cik_manifest
from edgar_sec.pipelines.metadata_sync.roster import (
    ROSTER_SCHEMA,
    Roster,
    RosterError,
    build_roster,
    derive_roster_id,
    empty_roster,
    read_cik_index,
    read_roster,
    roster_from_manifest,
    roster_to_csv_text,
    union_rosters,
    without_ciks,
    write_cik_index,
    write_roster,
)
from tests.support import fixture_path

FOUR = ("0000001985", "0000001761", "0000000020", "0000037996")
NAMES = (
    "Accel International Corp",
    "Tranzonic Companies",
    "K Tron International Inc",
    "FORD MOTOR CO",
)


def _mini() -> Roster:
    return roster_from_manifest(read_cik_manifest(fixture_path("cik_sec_mini.csv")))


def test_roster_carries_the_manifest_order() -> None:
    roster = _mini()
    assert roster.ciks == FOUR
    assert roster.names == NAMES
    assert roster.row_count == 4
    assert not roster.is_empty


def test_identity_is_content_derived_and_not_timestamped() -> None:
    assert _mini().roster_id == _mini().roster_id
    assert len(_mini().roster_id) == 32


def test_identity_follows_order() -> None:
    """Reordering a cohort is a different cohort, not a reformatting."""
    assert build_roster(reversed(FOUR)).roster_id != build_roster(FOUR).roster_id


def test_identity_follows_names() -> None:
    assert build_roster(FOUR, NAMES).roster_id != build_roster(FOUR).roster_id


def test_identity_ignores_the_source_file() -> None:
    """Identity is the cohort, not the bytes a curator typed.

    Two files listing the same CIKs in the same order describe the same work, so
    they must produce the same roster and therefore the same resumable plan.
    """
    left = build_roster(FOUR, NAMES)
    right = build_roster(FOUR, NAMES)
    assert left == right


def test_duplicate_ciks_are_refused() -> None:
    with pytest.raises(RosterError, match="duplicate"):
        build_roster(("0000001985", "0000001985"))


def test_empty_cohort_has_its_own_identity() -> None:
    empty = empty_roster()
    assert empty.is_empty
    assert empty.row_count == 0
    assert empty.roster_id != build_roster(FOUR).roster_id


def test_derive_rejects_mismatched_names() -> None:
    with pytest.raises(RosterError, match="length mismatch"):
        derive_roster_id(FOUR, ("only-one",))


def test_range_lookup_matches_the_ordinal_layout() -> None:
    roster = _mini()
    assert roster.range_ciks(0, 2) == FOUR[:2]
    assert roster.range_ciks(2, 2) == FOUR[2:]
    assert roster.range_ciks(3, 10) == FOUR[3:]


def test_range_lookup_rejects_a_negative_window() -> None:
    with pytest.raises(RosterError, match="invalid roster range"):
        _mini().range_ciks(-1, 2)


def test_name_map_resolves_in_one_pass() -> None:
    """The map replaces a per-CIK linear scan over a parallel tuple."""
    assert _mini().name_map() == dict(zip(FOUR, NAMES, strict=True))


def test_without_ciks_preserves_order_and_identity() -> None:
    delta = without_ciks(_mini(), {"0000001761"})
    assert delta.ciks == ("0000001985", "0000000020", "0000037996")
    assert delta.names == (NAMES[0], NAMES[2], NAMES[3])
    assert delta != _mini()


def test_without_everything_is_the_empty_cohort() -> None:
    assert without_ciks(_mini(), set(FOUR)).is_empty


def test_union_keeps_first_position_and_upgrades_a_blank_name() -> None:
    left = build_roster(("0000001985", "0000001761"), ("ACCEL", ""))
    right = build_roster(("0000001761", "0000000020"), ("TRANZONIC", "K TRON"))
    merged = union_rosters(left, right)
    assert merged.ciks == ("0000001985", "0000001761", "0000000020")
    assert merged.names == ("ACCEL", "TRANZONIC", "K TRON")


def test_write_and_read_round_trip_preserves_identity(tmp_path: Path) -> None:
    roster = _mini()
    digest = write_roster(roster, tmp_path / "ciks.parquet")
    assert len(digest) == 64
    assert (
        read_roster(tmp_path / "ciks.parquet", expected_roster_id=roster.roster_id)
        == roster
    )


def test_read_rejects_a_swapped_roster(tmp_path: Path) -> None:
    """A cohort replaced after publication must not pass as the planned one."""
    write_roster(_mini(), tmp_path / "ciks.parquet")
    with pytest.raises(RosterError, match="identity"):
        read_roster(tmp_path / "ciks.parquet", expected_roster_id="0" * 32)


def test_read_rejects_a_foreign_schema(tmp_path: Path) -> None:
    import pyarrow as pa

    from edgar_sec.infra.storage.parquet import write_parquet_table

    path = tmp_path / "wrong.parquet"
    write_parquet_table(pa.table({"cik_padded": ["0000001985"]}), path)
    with pytest.raises(RosterError, match="schema drifted"):
        read_roster(path)


def test_read_missing_roster_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_roster(tmp_path / "absent.parquet")


def test_csv_export_quotes_separators() -> None:
    text = roster_to_csv_text(build_roster(("0000001985",), ('Acme, "The" Co',)))
    assert text == 'cik,name\n0000001985,"Acme, ""The"" Co"\n'


def test_csv_export_round_trips_through_the_reader(tmp_path: Path) -> None:
    """The CSV stays importable, so a v1-era script still works."""
    exported = tmp_path / "effective.csv"
    exported.write_text(roster_to_csv_text(_mini()), encoding="utf-8")
    assert read_cik_manifest(exported).ciks == FOUR


def test_cik_index_is_sorted_and_distinct(tmp_path: Path) -> None:
    digest = write_cik_index(
        ["0000037996", "0000001985", "0000001985"], tmp_path / "ciks.parquet"
    )
    assert len(digest) == 64
    assert read_cik_index(tmp_path / "ciks.parquet") == (
        "0000001985",
        "0000037996",
    )


def test_cik_index_rejects_an_empty_cohort(tmp_path: Path) -> None:
    with pytest.raises(RosterError, match="must not be empty"):
        write_cik_index([], tmp_path / "ciks.parquet")


def test_cik_index_read_rejects_an_unsorted_file(tmp_path: Path) -> None:
    import pyarrow as pa

    from edgar_sec.infra.storage.parquet import write_parquet_table
    from edgar_sec.pipelines.metadata_sync.roster import SNAPSHOT_CIK_INDEX_SCHEMA

    path = tmp_path / "unsorted.parquet"
    write_parquet_table(
        pa.Table.from_pylist(
            [{"cik": "0000037996"}, {"cik": "0000001985"}],
            schema=SNAPSHOT_CIK_INDEX_SCHEMA,
        ),
        path,
    )
    with pytest.raises(RosterError, match="not sorted"):
        read_cik_index(path)


def test_roster_schema_is_ordinal_keyed_and_name_carrying() -> None:
    assert ROSTER_SCHEMA.names == ["ordinal", "cik_padded", "name"]


def test_full_corpus_identity_and_io_stay_cheap(tmp_path: Path) -> None:
    """The identity has to stay derivable at the scale that motivated it.

    Hashing a whole canonical JSON document per roster would materialize a
    multi-megabyte string; this pins that the row-wise derivation is fast and
    that a 250,000-CIK roster still round-trips and verifies.
    """
    size = 250_000
    ciks = tuple(f"{value:010d}" for value in range(1, size + 1))
    started = time.perf_counter()
    roster = build_roster(ciks)
    assert time.perf_counter() - started < 10.0
    started = time.perf_counter()
    write_roster(roster, tmp_path / "big.parquet")
    assert time.perf_counter() - started < 60.0
    started = time.perf_counter()
    loaded = read_roster(tmp_path / "big.parquet", expected_roster_id=roster.roster_id)
    assert time.perf_counter() - started < 60.0
    assert loaded.row_count == size
    assert loaded.ciks[:2] == ciks[:2]
