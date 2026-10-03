"""Unit tests for engine.selection.policy: the declarative quota profile.

The policy is the only place a form name, an era boundary, or a dimension
weight appears. These tests therefore pin two things: that it round-trips
exactly (a plan's recorded policy must be reloadable to the same fingerprint),
and that it rejects nonsense at construction rather than hours later inside a
selector.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from edgar_sec.engine.selection.policy import (
    KNOWN_DIMENSIONS,
    EraBand,
    SeedFiler,
    SelectionPolicy,
    auto_generate_policy,
    compute_seed_fingerprint,
    discover_policies,
    era_bands_for_range,
    load_seed_cik_csv,
    normalize_value,
)


def test_era_band_boundaries_are_half_open() -> None:
    """Adjacent bands must tile a range: the start year is in, the end is out."""
    band = EraBand(name="era_early", start_year=1995, end_year=2005)
    assert band.matches(1995, "1995-03-15")
    assert band.matches(2000, "2000-12-31")
    assert not band.matches(2005, "2005-01-01")
    assert not band.matches(1990, "1990-05-20")


def test_era_band_accepts_date_bounds() -> None:
    band = EraBand(name="era_sec_rule", start_date="2020-06-15", end_date="2024-01-01")
    assert band.matches(2020, "2020-06-15")
    assert band.matches(2022, "2022-01-01")
    assert not band.matches(2020, "2020-06-14")
    assert not band.matches(2024, "2024-01-01")


def test_era_band_requires_a_boundary() -> None:
    """A band with no bound would match every filing and empty the quota."""
    with pytest.raises(ValueError, match="must specify at least one boundary"):
        EraBand(name="invalid_band")


def test_era_band_requires_a_name() -> None:
    with pytest.raises(ValueError, match="non-empty string"):
        EraBand(name="", start_year=2000)


def test_policy_normalizes_forms_and_suffixes() -> None:
    policy = SelectionPolicy(
        corpus_id="filters",
        forms=["10-k", "10-K", " 20-f "],
        document_suffixes=[".TXT", "xml", "txt"],
    )
    assert policy.forms == ["10-K", "20-F"]
    assert policy.document_suffixes == ["txt", "xml"]


def test_policy_rejects_an_empty_form_list() -> None:
    with pytest.raises(ValueError, match="forms must contain at least one"):
        SelectionPolicy(corpus_id="invalid", forms=["  "])


def test_policy_rejects_unknown_dimensions_in_floors() -> None:
    with pytest.raises(ValueError, match="unknown policy dimensions"):
        SelectionPolicy(
            corpus_id="bad", forms=["10-K"], floors={"non_existent_dim": {"val": 10}}
        )


def test_policy_rejects_unknown_dimensions_inside_a_composite() -> None:
    """v1 validated only top-level keys.

    A typo inside a composite's filters passed construction and then produced a
    stratum nothing could ever match, so the floor silently underfilled.
    """
    with pytest.raises(ValueError, match="unknown policy dimensions"):
        SelectionPolicy(
            corpus_id="bad",
            forms=["10-K"],
            composites=[{"filters": {"erra": "modern"}, "min": 5}],
        )


def test_policy_rejects_an_out_of_range_cap() -> None:
    with pytest.raises(ValueError, match="must be in \\(0, 1\\]"):
        SelectionPolicy(corpus_id="c", forms=["10-K"], caps={"form": 1.5})
    with pytest.raises(ValueError, match="must be in \\(0, 1\\]"):
        SelectionPolicy(corpus_id="c", forms=["10-K"], caps={"form": 0.0})


def test_policy_rejects_non_positive_units_and_levels() -> None:
    with pytest.raises(ValueError, match="base_content_units must be positive"):
        SelectionPolicy(corpus_id="c", forms=["10-K"], base_content_units=0)
    with pytest.raises(ValueError, match="level must be at least 1"):
        SelectionPolicy(corpus_id="c", forms=["10-K"], level=0)


def test_policy_round_trips_to_the_same_fingerprint() -> None:
    policy = SelectionPolicy(
        corpus_id="custom_corpus",
        forms=["10-K", "20-F"],
        era_bands=[
            EraBand(name="band_1", start_year=2000, end_year=2010),
            EraBand(name="band_2", start_year=2010, end_year=2020),
        ],
        base_content_units=300,
        floors={"form": {"10-K": 50, "20-F": 20}},
        caps={"form": 0.8},
    )
    data = policy.to_dict()
    assert data["corpus_id"] == "custom_corpus"
    assert len(data["era_bands"]) == 2
    assert len(policy.policy_fingerprint) == 32

    restored = SelectionPolicy.from_dict(data)
    assert restored.corpus_id == policy.corpus_id
    assert [band.name for band in restored.era_bands] == ["band_1", "band_2"]
    assert restored.policy_fingerprint == policy.policy_fingerprint


def test_policy_write_and_reload_preserves_the_fingerprint(tmp_path: Path) -> None:
    policy = SelectionPolicy(corpus_id="written", forms=["10-K"], base_content_units=42)
    path = policy.write(tmp_path / "policy.json")
    assert SelectionPolicy.from_path(path).policy_fingerprint == (
        policy.policy_fingerprint
    )


def test_policy_fingerprint_changes_with_a_material_edit() -> None:
    policy = SelectionPolicy(corpus_id="c", forms=["10-K"], base_content_units=10)
    before = policy.policy_fingerprint
    policy.base_content_units = 11
    assert policy.policy_fingerprint != before


@pytest.mark.parametrize(
    "retired",
    ["seed_groups", "weights", "value_weights", "policy_schema_version"],
)
def test_a_retired_key_is_refused_rather_than_ignored(retired: str) -> None:
    """A draft carrying a key selection never reads must fail to load.

    Dropping the key and loading the rest would publish a plan from a policy
    whose own text describes a weighting, a seed grouping, or a schema that
    nothing applies. Failing closed is the only reading that is honest.
    """
    document = {"corpus_id": "c", "forms": ["10-K"], retired: []}
    with pytest.raises(ValueError, match=retired):
        SelectionPolicy.from_dict(document)


def test_known_dimensions_cover_every_reported_feature() -> None:
    """A dimension the snapshot writes but the policy rejects is unusable."""
    for dimension in (
        "era",
        "form_family",
        "size_band",
        "lifecycle_class",
        "company_family",
    ):
        assert dimension in KNOWN_DIMENSIONS


def test_validate_dimensions_reports_a_snapshot_mismatch() -> None:
    policy = SelectionPolicy(
        corpus_id="c", forms=["10-K"], floors={"era": {"modern": 2}}
    )
    with pytest.raises(ValueError, match="absent from snapshot"):
        policy.validate_dimensions({"form", "era_bands"})
    policy.validate_dimensions({"form", "era"})


# ------------------------------------------------------------------ seed CSV


def test_load_seed_cik_csv_normalizes_and_validates(tmp_path: Path) -> None:
    path = tmp_path / "seed-cik.csv"
    path.write_text(
        "cik,seed_group,coverage_tags,notes\n"
        "37996,automotive,large-filer,Ford\n"
        "0000078003,healthcare,pharma,Historical\n",
        encoding="utf-8",
    )
    seeds = load_seed_cik_csv(path)
    assert set(seeds) == {"0000037996", "0000078003"}
    assert seeds["0000037996"].seed_group == "automotive"
    assert seeds["0000078003"].notes == "Historical"


def test_load_seed_cik_csv_rejects_duplicate_ciks(tmp_path: Path) -> None:
    """37996 and 0000037996 are the same registrant, so this is a real conflict."""
    path = tmp_path / "seed-cik.csv"
    path.write_text(
        "cik,seed_group\n0000037996,group1\n37996,group2\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="duplicate CIK"):
        load_seed_cik_csv(path)


def test_load_seed_cik_csv_rejects_a_missing_cik_column(tmp_path: Path) -> None:
    path = tmp_path / "seed-cik.csv"
    path.write_text("ticker\nAAPL\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required 'cik' column"):
        load_seed_cik_csv(path)


def test_load_seed_cik_csv_reports_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="seed CIK file not found"):
        load_seed_cik_csv(tmp_path / "absent.csv")


def test_seed_fingerprint_is_stable_across_row_order() -> None:
    """The hash is over values, not file order.

    Re-sorting the manifest must not invalidate every plan built from it.
    """
    forward = {
        "0000000001": SeedFiler(cik="0000000001", seed_group="a"),
        "0000000002": SeedFiler(cik="0000000002", seed_group="b"),
    }
    reversed_order = dict(reversed(list(forward.items())))
    assert compute_seed_fingerprint(forward) == compute_seed_fingerprint(reversed_order)
    assert len(compute_seed_fingerprint(forward)) == 32


def test_seed_fingerprint_changes_with_any_field() -> None:
    base = {"0000000001": SeedFiler(cik="0000000001", seed_group="a")}
    edited = {"0000000001": SeedFiler(cik="0000000001", seed_group="b")}
    assert compute_seed_fingerprint(base) != compute_seed_fingerprint(edited)


# ------------------------------------------------------------- normalization


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, "none"),
        (True, "true"),
        (False, "false"),
        ("  Mixed Case ", "mixed case"),
        (42, "42"),
    ],
)
def test_normalize_value(raw: object, expected: str) -> None:
    assert normalize_value(raw) == expected


def test_normalize_value_collapses_missing_and_the_none_literal() -> None:
    """Otherwise a floor on 'none' counts as unmet no matter how many rows lack it."""
    assert normalize_value(None) == normalize_value("None")


# --------------------------------------------------------------- generation


def test_auto_generate_policy_tiles_the_observed_year_range() -> None:
    policy = auto_generate_policy("abcdef1234", ["10-K", "8-K"], 1995, 2010)
    assert policy.corpus_id == "corpus_abcdef12"
    assert policy.forms == ["10-K", "8-K"]
    years = [(band.start_year, band.end_year) for band in policy.era_bands]
    assert years[0][0] == 1995
    assert years[-1][1] == 2011
    for (_, end), (next_start, _) in itertools.pairwise(years):
        assert end == next_start, "bands must tile without a gap"


def test_auto_generate_policy_gives_each_short_year_its_own_band() -> None:
    policy = auto_generate_policy("catalog1234", ["10-K"], 2020, 2022)
    assert [band.name for band in policy.era_bands] == ["2020", "2021", "2022"]


def test_auto_generate_policy_scales_units_with_the_year_span() -> None:
    narrow = auto_generate_policy("catalog1234", ["10-K"], 2018, 2020)
    wide = auto_generate_policy("catalog1234", ["10-K"], 1995, 2020)
    assert narrow.base_content_units < wide.base_content_units


def test_auto_generate_policy_rejects_an_inverted_range() -> None:
    with pytest.raises(ValueError, match="year range is inverted"):
        auto_generate_policy("catalog1234", ["10-K"], 2020, 2010)


def test_auto_generate_policy_writes_when_asked(tmp_path: Path) -> None:
    destination = tmp_path / "nested" / "policy.json"
    auto_generate_policy("catalog1234", ["10-K"], 2015, 2020, dest=destination)
    assert json.loads(destination.read_text(encoding="utf-8"))["corpus_id"]


# ----------------------------------------------------------------- discovery


def test_discover_policies_summarizes_valid_documents(tmp_path: Path) -> None:
    SelectionPolicy(corpus_id="found", forms=["10-K"]).write(tmp_path / "a.json")
    summaries = discover_policies([tmp_path])
    assert [entry["name"] for entry in summaries] == ["a.json"]
    assert summaries[0]["corpus_id"] == "found"
    assert len(summaries[0]["policy_fingerprint"]) == 32


def test_discover_policies_skips_unrelated_json(tmp_path: Path) -> None:
    """A policy directory may legitimately hold other JSON.

    Raising here would make the operator menu unusable, so a non-policy file is
    skipped rather than reported.
    """
    (tmp_path / "notes.json").write_text('{"hello": "world"}', encoding="utf-8")
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    SelectionPolicy(corpus_id="found", forms=["10-K"]).write(tmp_path / "a.json")
    assert [entry["name"] for entry in discover_policies([tmp_path])] == ["a.json"]


def test_discover_policies_ignores_a_missing_directory(tmp_path: Path) -> None:
    assert discover_policies([tmp_path / "absent"]) == []


def test_discover_policies_does_not_double_count_overlapping_dirs(
    tmp_path: Path,
) -> None:
    SelectionPolicy(corpus_id="found", forms=["10-K"]).write(tmp_path / "a.json")
    assert len(discover_policies([tmp_path, tmp_path])) == 1


# --- the date selection and the derived-band mode ---------------------------


def test_a_policy_declares_no_date_selection_by_default() -> None:
    """Absent means no date predicate, not a selection of the whole corpus."""
    policy = SelectionPolicy(corpus_id="c", forms=["10-K"])
    assert policy.date_selection == []
    assert policy.date_selection_clauses == ()
    assert policy.date_selection_text == ""


def test_a_policy_reads_an_absent_date_selection_as_no_predicate() -> None:
    """A document written before the field existed is still a valid policy."""
    data = SelectionPolicy(corpus_id="c", forms=["10-K"]).to_dict()
    data.pop("date_selection")
    assert SelectionPolicy.from_dict(data).date_selection == []


def test_a_policy_canonicalizes_its_declared_date_selection() -> None:
    """A hand-edited draft fingerprints as the parsed selection.

    A draft is edited by people, who reorder and re-spell. Two files that mean
    the same thing must produce one plan id, or every cosmetic edit forks a
    duplicate bundle of the same rows.
    """
    declared = [
        {
            "kind": "recurring",
            "granularity": "quarter",
            "values": [1],
            "start_year": None,
            "end_year": None,
        },
        {"kind": "absolute", "start_date": "2024-01-01", "end_date": "2024-12-31"},
    ]
    reordered = [
        {"kind": "absolute", "start_date": "2024-01-01", "end_date": "2024-12-31"},
        {
            "kind": "recurring",
            "granularity": "quarter",
            "values": [1],
            "start_year": None,
            "end_year": None,
        },
    ]
    from_dict = SelectionPolicy.from_dict(
        {
            **SelectionPolicy(corpus_id="c", forms=["10-K"]).to_dict(),
            "date_selection": declared,
        }
    )
    same = SelectionPolicy.from_dict(
        {
            **SelectionPolicy(corpus_id="c", forms=["10-K"]).to_dict(),
            "date_selection": reordered,
        }
    )
    assert from_dict.policy_fingerprint == same.policy_fingerprint
    # Absolute clauses sort ahead of recurring ones, so the text is stable
    # regardless of the order a hand-edited document listed them in.
    assert from_dict.date_selection_text == "2024-01-01..2024-12-31,@Q1"


def test_a_policy_rejects_a_malformed_date_selection() -> None:
    with pytest.raises(ValueError, match="date clause kind"):
        SelectionPolicy(
            corpus_id="c",
            forms=["10-K"],
            date_selection=[{"kind": "era", "name": "modern"}],
        )


def test_an_empty_era_band_list_means_derived_not_unstratified() -> None:
    policy = SelectionPolicy(corpus_id="c", forms=["10-K"])
    assert policy.derives_era_bands
    resolved = policy.with_era_bands([EraBand(name="modern", start_year=2010)])
    assert not resolved.derives_era_bands
    assert [band.name for band in resolved.era_bands] == ["modern"]


def test_resolving_bands_leaves_the_original_policy_untouched() -> None:
    """The draft on disk must keep asking for derived bands.

    If resolution mutated the policy, re-reading the draft would find explicit
    bands and the automatic mode would silently become permanent.
    """
    policy = SelectionPolicy(corpus_id="c", forms=["10-K"])
    resolved = policy.with_era_bands(era_bands_for_range(1999, 2024))
    assert policy.era_bands == []
    assert resolved.era_bands
    assert policy.policy_fingerprint != resolved.policy_fingerprint


def test_resolving_bands_refuses_to_produce_none() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        SelectionPolicy(corpus_id="c", forms=["10-K"]).with_era_bands([])


def test_era_bands_for_range_refuses_an_inverted_range() -> None:
    with pytest.raises(ValueError, match="inverted"):
        era_bands_for_range(2024, 1999)


def test_derived_bands_tile_the_range_without_gaps_or_overlap() -> None:
    bands = era_bands_for_range(1999, 2024)
    assert bands[0].start_year == 1999
    assert bands[-1].end_year == 2025
    for earlier, later in itertools.pairwise(bands):
        assert earlier.end_year == later.start_year


def test_a_menu_summary_says_what_each_draft_selects(tmp_path: Path) -> None:
    """Two drafts that differ only in dates must be distinguishable in a menu."""
    quiet = SelectionPolicy(corpus_id="quiet", forms=["10-K"])
    scoped = SelectionPolicy.from_dict(
        {
            **quiet.to_dict(),
            "corpus_id": "scoped",
            "date_selection": [
                {
                    "kind": "recurring",
                    "granularity": "quarter",
                    "values": [1],
                    "start_year": None,
                    "end_year": None,
                }
            ],
        }
    )
    quiet.write(tmp_path / "quiet.json")
    scoped.write(tmp_path / "scoped.json")
    summaries = {entry["corpus_id"]: entry for entry in discover_policies([tmp_path])}
    assert summaries["quiet"]["date_selection_text"] == ""
    assert summaries["quiet"]["derives_era_bands"] is True
    assert summaries["quiet"]["era_band_count"] == 0
    assert summaries["scoped"]["date_selection_text"] == "@Q1"
    assert summaries["scoped"]["policy_fingerprint"] != quiet.policy_fingerprint
