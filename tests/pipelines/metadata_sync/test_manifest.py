"""CIK input compilation tests.

Compilation is where a curated file becomes the cohort a plan runs over, so these
tests pin the three properties everything downstream trusts: the cohort identity
is unchanged from the parser this replaced, an unusable cell is rejected rather
than turned into a registrant, and recompiling an unchanged input reuses what it
produced last time.

The pinned identities are the point of the first group. They were recorded from
the row-by-row parser before it was removed, so they are an oracle that no longer
depends on the code under test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.pipelines.metadata_sync.manifest import (
    cik_cohort_key,
    compile_cik_cohort,
    count_cohort_rows,
)
from edgar_sec.pipelines.metadata_sync.paths import (
    resolve_metadata_paths,
)
from tests.support import fixture_path

#: Recorded from the row-by-row parser before it was deleted.
LEGACY_IDENTITIES = {
    "cik_sec_mini.csv": ("0554eb6d91ecc97326ea0f7e51ae7f59", 4, 3, 1),
    "catalog/cik_sample.csv": ("36cdabbe2346c5462f27242bc5f9afc3", 6, 0, 0),
    "company_family/seed_ciks.csv": ("467aca2de994556b40d6b13dd1041999", 10, 0, 0),
}


def _paths(root: Path):
    return resolve_metadata_paths(root)


def _write(root: Path, text: str, name: str = "input.csv") -> Path:
    path = root / name
    path.write_text(text, encoding="utf-8")
    return path


# ------------------------------------------------------------------ identity


@pytest.mark.parametrize("fixture", sorted(LEGACY_IDENTITIES))
def test_compiled_identity_matches_the_parser_it_replaced(
    tmp_path: Path, fixture: str
) -> None:
    """A curated file must compile to the cohort the row-by-row parser produced.

    Rows, rejection count and duplicate count are pinned too, because an identity
    that happened to match while the cohort differed would be a coincidence.
    """
    roster_id, rows, rejected, duplicates = LEGACY_IDENTITIES[fixture]
    cohort = compile_cik_cohort(fixture_path(fixture), metadata_paths=_paths(tmp_path))
    assert cohort.roster_id == roster_id
    assert cohort.row_count == rows
    assert cohort.rejected_row_count == rejected
    assert cohort.duplicate_row_count == duplicates


def test_ordinal_order_is_the_manifest_order(tmp_path: Path) -> None:
    cohort = compile_cik_cohort(
        fixture_path("cik_sec_mini.csv"), metadata_paths=_paths(tmp_path)
    )
    assert cohort.roster.range_ciks(0, cohort.row_count) == (
        "0000001985",
        "0000001761",
        "0000000020",
        "0000037996",
    )


# -------------------------------------------------------------------- the guard


def test_cells_that_only_look_like_ciks_are_rejected(tmp_path: Path) -> None:
    """A cast alone would turn each of these into a real, wrong registrant.

    ``try_cast`` reads ``12.5`` as 13, ``1e5`` as 100000 and ``0x10`` as 16 --
    all valid CIKs, so an unguarded compile would publish a cohort containing
    registrants the curator never named, and nothing downstream would notice.
    """
    path = _write(
        tmp_path,
        "cik,name\n"
        "1985,Real Co\n"
        "12.5,Twelve Point Five\n"
        "1e5,Scientific\n"
        "0x10,Hex\n"
        "1_985,Underscored\n"
        "+1761,Leading Plus\n"
        "abc,Not A CIK\n"
        ",Empty\n"
        "0,Zero\n"
        "99999999999,Too Large\n"
        "37996,Real Two\n",
    )
    cohort = compile_cik_cohort(path, metadata_paths=_paths(tmp_path))
    assert cohort.roster.range_ciks(0, cohort.row_count) == (
        "0000001985",
        "0000037996",
    )
    assert cohort.rejected_row_count == 9


def test_empty_cell_is_not_cik_zero(tmp_path: Path) -> None:
    """``Cik.from_raw("")`` yields CIK zero, which must not become a registrant."""
    path = _write(tmp_path, "cik,name\n1985,Acme\n,Empty Cell\n0,Actual Zero\n")
    cohort = compile_cik_cohort(path, metadata_paths=_paths(tmp_path))
    assert cohort.roster.range_ciks(0, cohort.row_count) == ("0000001985",)


def test_one_registrant_written_two_ways_is_one_member(tmp_path: Path) -> None:
    """Padding is applied last, so duplicates are matched on the CIK value.

    ``1985`` and ``0000001985`` are one registrant. Partitioning deduplication on
    the text would let both through and then collide them into a duplicate, since
    the cohort's own key is the padded string.
    """
    path = _write(
        tmp_path,
        "cik,name\n1985,Unpadded\n0000001985,Padded\n1761,Other\n",
    )
    cohort = compile_cik_cohort(path, metadata_paths=_paths(tmp_path))
    assert cohort.roster.range_ciks(0, cohort.row_count) == (
        "0000001985",
        "0000001761",
    )
    assert cohort.duplicate_row_count == 1
    # The first spelling wins, so the curated name is the one a curator read first.
    assert cohort.roster.name_map()["0000001985"] == "Unpadded"


# ------------------------------------------------------------------- the shape


def test_ragged_and_wide_rows_do_not_shift_the_columns(tmp_path: Path) -> None:
    """A short row and a long row must not move any other row's name.

    A short row has no name and must not borrow the next row's. A long row keeps
    its second field and drops the surplus, because a two-column reader has always
    meant "the first two fields", and dropping beats failing the ingest over one
    extra column.
    """
    path = _write(
        tmp_path,
        "cik,name\n"
        "1985\n"  # short: no separator, so no name
        '1761,"Tranzonic, Companies"\n'  # quoted separator
        "20,K Tron\n"
        "37996,FORD,EXTRA,ALSO EXTRA\n",  # wide: more fields than the header
    )
    cohort = compile_cik_cohort(path, metadata_paths=_paths(tmp_path))
    assert cohort.roster.range_rows(0, cohort.row_count) == (
        ("0000001985", ""),
        ("0000001761", "Tranzonic, Companies"),
        ("0000000020", "K Tron"),
        ("0000037996", "FORD"),
    )


def test_header_is_detected_and_a_headerless_file_keeps_its_first_row(
    tmp_path: Path,
) -> None:
    with_header = _write(tmp_path, "cik,name\n1985,Accel\n1761,Other\n", "a.csv")
    assert (
        compile_cik_cohort(with_header, metadata_paths=_paths(tmp_path)).row_count == 2
    )

    without = _write(tmp_path, "1985,Accel\n1761,Other\n", "b.csv")
    cohort = compile_cik_cohort(without, metadata_paths=_paths(tmp_path))
    assert cohort.row_count == 2
    assert cohort.roster.range_ciks(0, 2) == ("0000001985", "0000001761")


def test_non_ascii_names_survive(tmp_path: Path) -> None:
    path = _write(tmp_path, 'cik,name\n1985,"Café naïve – 株式会社"\n1761,"Ünïcödé"\n')
    cohort = compile_cik_cohort(path, metadata_paths=_paths(tmp_path))
    assert cohort.roster.name_map()["0000001985"] == "Café naïve – 株式会社"


# ------------------------------------------------------------------- the limit


def test_limit_binds_identity_before_the_cohort_is_named(tmp_path: Path) -> None:
    """A bounded cohort and the full cohort over one file are two cohorts."""
    source = fixture_path("cik_sec_mini.csv")
    full = compile_cik_cohort(source, metadata_paths=_paths(tmp_path))
    limited = compile_cik_cohort(source, limit=2, metadata_paths=_paths(tmp_path))
    assert limited.roster_id != full.roster_id
    assert limited.row_count == 2
    assert limited.roster.range_ciks(0, 2) == ("0000001985", "0000001761")
    assert limited.selected_limit == 2
    # Same source file, so the fingerprint is the same; only the cohort differs.
    assert limited.input_fingerprint == full.input_fingerprint


def test_limit_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="limit"):
        compile_cik_cohort(
            fixture_path("cik_sec_mini.csv"),
            limit=0,
            metadata_paths=_paths(tmp_path),
        )


def test_cohort_key_separates_a_bounded_cohort(tmp_path: Path) -> None:
    assert cik_cohort_key("abc") == "abc"
    assert cik_cohort_key("abc", 5) == "abc-limit-5"


# ------------------------------------------------------------------- reuse


def test_recompiling_an_unchanged_input_reuses_the_dataset(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    first = compile_cik_cohort(fixture_path("cik_sec_mini.csv"), metadata_paths=paths)
    dataset = first.roster.dataset
    dataset_mtime = dataset.stat().st_mtime_ns

    second = compile_cik_cohort(fixture_path("cik_sec_mini.csv"), metadata_paths=paths)
    assert second.roster_id == first.roster_id
    assert second.roster.dataset == dataset
    assert dataset.stat().st_mtime_ns == dataset_mtime, "dataset was rewritten"
    assert second.rejected_row_count == first.rejected_row_count


def test_editing_the_input_recompiles(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    first = compile_cik_cohort(fixture_path("cik_sec_mini.csv"), metadata_paths=paths)
    edited = _write(tmp_path, "cik,name\n1985,Accel\n", "edited.csv")
    second = compile_cik_cohort(edited, metadata_paths=paths)
    assert second.roster_id != first.roster_id
    assert second.row_count == 1


def test_a_tampered_dataset_is_recompiled_not_trusted(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    first = compile_cik_cohort(fixture_path("cik_sec_mini.csv"), metadata_paths=paths)
    first.roster.dataset.write_bytes(b"not a parquet file")
    again = compile_cik_cohort(fixture_path("cik_sec_mini.csv"), metadata_paths=paths)
    assert again.roster_id == first.roster_id
    assert again.row_count == 4


# ------------------------------------------------------------------- failures


def test_missing_input_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        compile_cik_cohort(tmp_path / "absent.csv", metadata_paths=_paths(tmp_path))


def test_input_with_no_usable_ciks_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, "cik,name\nabc,nope\n,also nope\n")
    with pytest.raises(ValueError, match="no usable CIKs"):
        compile_cik_cohort(path, metadata_paths=_paths(tmp_path))


# --------------------------------------------------------------------- listing


def test_counting_an_input_does_not_compile_it(tmp_path: Path) -> None:
    """Listing candidates must stay cheap and must not leave an artifact behind."""
    paths = _paths(tmp_path)
    source = fixture_path("cik_sec_mini.csv")
    assert count_cohort_rows(source) == 4
    assert not paths.cohorts_root.exists()

    compile_cik_cohort(source, metadata_paths=paths)
    assert paths.cohorts_root.exists()


def test_counting_deduplicates_by_value(tmp_path: Path) -> None:
    path = _write(tmp_path, "cik,name\n1985,A\n0000001985,B\n1761,C\n1761,D\n")
    assert count_cohort_rows(path) == 2


def test_counting_a_missing_or_empty_input_is_zero(tmp_path: Path) -> None:
    assert count_cohort_rows(tmp_path / "absent.csv") == 0
    assert count_cohort_rows(_write(tmp_path, "cik,name\nabc,nope\n")) == 0
