"""The content-addressed cohort dataset: identity over the ordered cohort and its
names, and a round trip faithful enough that a re-derived identity still matches.
"""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import pytest

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.parquet import write_parquet_table
from edgar_sec.pipelines.metadata_sync.roster import (
    ROSTER_SCHEMA,
    Roster,
    RosterError,
    cohort_record_to_roster,
    derive_roster_id,
    empty_roster,
    read_cik_index,
    read_roster,
    roster_to_csv_text,
    write_cik_index,
    write_roster,
    write_roster_rows,
)
from tests.pipelines.metadata_sync.cohort_support import publish_test_cohort
from tests.support import fixture_path
from tests.support import roster_of

FOUR = ("0000001985", "0000001761", "0000000020", "0000037996")
NAMES = (
    "Accel International Corp",
    "Tranzonic Companies",
    "K Tron International Inc",
    "FORD MOTOR CO",
)


def _mini() -> Roster:
    return roster_of(FOUR, NAMES)


def _all_rows(roster: Roster) -> tuple[tuple[str, str], ...]:
    return roster.range_rows(0, roster.row_count)


def test_roster_carries_the_cohort_order() -> None:
    roster = _mini()
    assert roster.range_ciks(0, roster.row_count) == FOUR
    assert _all_rows(roster) == tuple(zip(FOUR, NAMES, strict=True))
    assert roster.row_count == 4
    assert not roster.is_empty


def test_identity_is_content_derived_and_not_timestamped() -> None:
    first, second = _mini(), _mini()
    assert first.roster_id == second.roster_id
    assert len(first.roster_id) == 32
    # Equality is identity and size, not the path each write happened to land on.
    assert (first.roster_id, first.row_count) == (second.roster_id, second.row_count)


def test_identity_follows_order() -> None:
    """Reordering a cohort is a different cohort, not a reformatting."""
    assert roster_of(reversed(FOUR)).roster_id != roster_of(FOUR).roster_id


def test_identity_follows_names() -> None:
    assert roster_of(FOUR, NAMES).roster_id != roster_of(FOUR).roster_id


def test_duplicate_ciks_are_refused(tmp_path: Path) -> None:
    with pytest.raises(RosterError, match="duplicate"):
        write_roster_rows(
            [("0000001985", "A"), ("0000001985", "B")], tmp_path / "ciks.parquet"
        )


def test_empty_cohort_has_its_own_identity() -> None:
    empty = empty_roster()
    assert empty.is_empty
    assert empty.row_count == 0
    assert empty.dataset is None
    assert empty.range_rows(0, 5) == ()
    assert empty.roster_id != roster_of(FOUR).roster_id


def test_identity_derivation_needs_a_dataset(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        derive_roster_id(tmp_path / "absent.parquet")


def test_range_lookup_matches_the_ordinal_layout() -> None:
    roster = _mini()
    assert roster.range_ciks(0, 2) == FOUR[:2]
    assert roster.range_ciks(2, 2) == FOUR[2:]
    assert roster.range_ciks(3, 10) == FOUR[3:]
    assert roster.range_ciks(4, 1) == ()
    assert roster.range_rows(1, 2) == tuple(zip(FOUR[1:3], NAMES[1:3], strict=True))


def test_range_lookup_rejects_a_negative_window() -> None:
    with pytest.raises(RosterError, match="invalid roster range"):
        _mini().range_ciks(-1, 2)


def test_range_lookup_spans_row_group_boundaries(tmp_path: Path) -> None:
    """A window that crosses row groups returns every row exactly once, in order."""
    many = tuple(f"{value:010d}" for value in range(1, 5_001))
    roster = write_roster_rows(
        [(cik, f"N{index}") for index, cik in enumerate(many)],
        tmp_path / "many.parquet",
    )[0]
    window = roster.range_rows(1_234, 2_500)
    assert len(window) == 2_500
    assert [cik for cik, _ in window] == list(many[1_234:3_734])


def test_name_map_resolves_in_one_pass() -> None:
    """The map replaces a per-CIK linear scan over a parallel tuple."""
    assert _mini().name_map() == dict(zip(FOUR, NAMES, strict=True))


def test_iter_rows_streams_the_whole_cohort_in_order() -> None:
    assert tuple(_mini().iter_rows()) == tuple(zip(FOUR, NAMES, strict=True))


def test_write_and_read_round_trip_preserves_identity(tmp_path: Path) -> None:
    roster = _mini()
    digest = write_roster(roster, tmp_path / "ciks.parquet")
    assert len(digest) == 64
    reopened = read_roster(
        tmp_path / "ciks.parquet", expected_roster_id=roster.roster_id
    )
    assert reopened.roster_id == roster.roster_id
    assert reopened.row_count == roster.row_count
    assert _all_rows(reopened) == _all_rows(roster)


def test_publish_carries_the_cohort_identity_to_the_destination(
    tmp_path: Path,
) -> None:
    source, _digest = write_roster_rows(
        [("0000099999", "X")], tmp_path / "other.parquet"
    )
    assert write_roster(source, tmp_path / "ciks.parquet")
    published = read_roster(
        tmp_path / "ciks.parquet", expected_roster_id=source.roster_id
    )
    assert published.range_ciks(0, published.row_count) == ("0000099999",)


def test_publish_refuses_a_roster_whose_dataset_contradicts_its_identity(
    tmp_path: Path,
) -> None:
    """A cohort whose file does not hash to the identity it claims is not published."""
    honest, _digest = write_roster_rows(
        [("0000099999", "X")], tmp_path / "other.parquet"
    )
    forged = Roster(
        roster_id="0" * 32, row_count=honest.row_count, dataset=honest.dataset
    )
    with pytest.raises(RosterError, match="does not carry identity"):
        write_roster(forged, tmp_path / "ciks.parquet")


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
    text = roster_to_csv_text(roster_of(("0000001985",), ('Acme, "The" Co',)))
    assert text == 'cik,name\n0000001985,"Acme, ""The"" Co"\n'


def test_cohort_adapter_keeps_the_two_roster_identities_distinct(
    tmp_path: Path,
) -> None:
    record, paths, roster = publish_test_cohort(
        fixture_path("cik_sec_mini.csv"), tmp_path
    )
    adapted = cohort_record_to_roster(record, paths)
    assert adapted.roster_id == roster.roster_id
    assert adapted.roster_id != record.roster_id
    assert adapted.row_count == record.row_count == record.distinct_cik_count


def test_cohort_adapter_verifies_dataset_digest(tmp_path: Path) -> None:
    record, paths, _roster = publish_test_cohort(
        fixture_path("cik_sec_mini.csv"), tmp_path
    )
    with pytest.raises(RosterError, match="digest does not match"):
        cohort_record_to_roster(replace(record, dataset_sha256="0" * 64), paths)


@pytest.mark.parametrize("field", ["row_count", "distinct_cik_count"])
def test_cohort_adapter_verifies_recorded_row_counts(
    tmp_path: Path, field: str
) -> None:
    record, paths, _roster = publish_test_cohort(
        fixture_path("cik_sec_mini.csv"), tmp_path
    )
    with pytest.raises(RosterError, match="does not match dataset"):
        cohort_record_to_roster(replace(record, **{field: record.row_count + 1}), paths)


def test_cohort_adapter_rejects_a_foreign_dataset_schema(tmp_path: Path) -> None:
    import pyarrow as pa

    from edgar_sec.infra.storage.cohort.paths import resolve_cohort_paths

    record, paths, _roster = publish_test_cohort(
        fixture_path("cik_sec_mini.csv"), tmp_path
    )
    foreign = paths.cohorts_root / "foreign.parquet"
    write_parquet_table(pa.table({"cik_padded": ["0000000001"]}), foreign)
    altered = replace(
        record,
        dataset_path=paths.relative_path(foreign),
        dataset_sha256=file_sha256(foreign),
        row_count=1,
        distinct_cik_count=1,
    )
    with pytest.raises(RosterError, match="schema drifted"):
        cohort_record_to_roster(altered, resolve_cohort_paths(tmp_path))


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
    """Row-wise derivation, not a materialized multi-megabyte canonical document."""
    size = 250_000
    ciks = tuple(f"{value:010d}" for value in range(1, size + 1))
    started = time.perf_counter()
    roster, _digest = write_roster_rows(
        [(cik, "") for cik in ciks], tmp_path / "big.parquet"
    )
    assert time.perf_counter() - started < 10.0
    started = time.perf_counter()
    write_roster(roster, tmp_path / "copy.parquet")
    assert time.perf_counter() - started < 60.0
    started = time.perf_counter()
    loaded = read_roster(tmp_path / "copy.parquet", expected_roster_id=roster.roster_id)
    assert time.perf_counter() - started < 60.0
    assert loaded.row_count == size
    assert loaded.range_ciks(0, 2) == ciks[:2]
