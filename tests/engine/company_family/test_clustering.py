"""Unit tests for company-family normalization and clustering.

The clustering tests pin the *invariants* that matter for sampling rather than
exact hash values: one economic entity collapses to a single family, and
unrelated companies that share one word stay apart. The last is the subtle one
-- a naive prefix rule merges "Honda Motor" with "Honda Auto" and silently
skews any quota-balanced sample.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from edgar_sec.domain.taxonomy.legal_forms import LEGAL_FORMS
from edgar_sec.engine.company_family.clustering import (
    CompanyFamilyIndex,
    CompanyFamilyInfo,
    family_id_for,
)
from edgar_sec.engine.company_family.normalizer import (
    clean_key,
    count_structural_tokens,
    is_variant,
    mine_structural_vocabulary,
    normalize_name,
    normalized_body,
    post_normalize,
    strip_legal_forms,
)


@pytest.fixture(scope="module")
def corpus() -> list[tuple[str, str]]:
    return [
        ("0001383094", "Santander Drive Auto Receivables LLC"),
        ("0001398244", "Santander Drive Auto Receivables Trust 2007-2"),
        ("0001570776", "Santander Drive Auto Receivables Trust 2013-2"),
        ("0001600109", "Santander Drive Auto Receivables Trust 2014-4"),
        ("0000019617", "JPMorgan Chase & Co"),
        (
            "0001319760",
            "JPMorgan Chase Commercial Mortgage Securities Corp Series 2005-LDP3",
        ),
        ("0000895421", "Morgan Stanley"),
        ("0001387224", "Morgan Stanley ABS Capital I Inc. Trust 2007-HE4"),
        ("0001566138", "Honda Auto Receivables 2013-1 Owner Trust"),
        ("0000866787", "AutoZone Inc"),
    ]


@pytest.fixture(scope="module")
def index(corpus: list[tuple[str, str]]) -> CompanyFamilyIndex:
    return CompanyFamilyIndex.build_from_records(corpus)


# --- normalization --------------------------------------------------------


def test_normalize_expands_unambiguous_abbreviations() -> None:
    tokens = normalize_name("J.P. Morgan Chase Commercial Mtg Sec Tr 2011-C5")
    assert "mortgage" in tokens
    assert "security" in tokens  # "Sec" expands then the plural fold applies


def test_normalize_folds_plurals() -> None:
    assert "receivable" in normalize_name("Santander Drive Auto Receivables LLC")


def test_normalize_applies_context_rules() -> None:
    """An ambiguous abbreviation expands only in a supporting context."""
    commercial = normalize_name("Some Commercial Mortgage Pass Through Trust")
    assert "commercial" in commercial
    assert "mortgage" in commercial
    assert "through" in commercial


def test_normalize_leaves_ambiguous_tokens_alone_outside_context() -> None:
    """The same token must not expand where the evidence is absent."""
    tokens = normalize_name("trading volume analytics")
    assert "trust" not in tokens


@pytest.mark.parametrize("raw", ["", "   ", "()", "/DE/"])
def test_normalize_handles_degenerate_input(raw: str) -> None:
    assert isinstance(normalize_name(raw), list)


def test_post_normalize_collapses_series_markers() -> None:
    # 2011 is numeric -> D; c5 is alphanumeric so it survives intact;
    # iv is a roman numeral -> R; x is a single letter -> S
    assert post_normalize(["2011", "c5", "iv", "x"]) == ["D", "c5", "R", "S"]
    assert post_normalize(["keep"]) == ["keep"]


def test_strip_legal_forms_removes_suffixes() -> None:
    assert strip_legal_forms(["acme", "holdings", "inc"]) == ["acme"]


def test_normalized_body_runs_the_full_chain() -> None:
    assert normalized_body("Santander Drive Auto Receivables LLC") == [
        "santander",
        "drive",
        "auto",
        "receivable",
    ]


def test_mine_structural_vocabulary_returns_a_frozenset(
    corpus: list[tuple[str, str]],
) -> None:
    vocab = mine_structural_vocabulary(
        [n for _, n in corpus], min_name_len=3, min_tail_freq=1
    )
    assert isinstance(vocab, frozenset)
    assert vocab, "expected structural vocabulary from a series-name corpus"
    assert not (vocab & LEGAL_FORMS), "legal forms are stripped before mining"


def test_mine_structural_vocabulary_protects_head_words(
    corpus: list[tuple[str, str]],
) -> None:
    """A word that heads its own family must not be mined as structural."""
    vocab = mine_structural_vocabulary(
        [n for _, n in corpus], min_name_len=3, min_tail_freq=1
    )
    for protected in ("santander", "morgan", "honda", "autozone", "stanley"):
        assert protected not in vocab, protected


def test_structural_helpers_agree_with_the_pipeline(
    corpus: list[tuple[str, str]],
) -> None:
    vocab = frozenset({"trust", "series", "receivable"})
    body = normalized_body("Santander Drive Auto Receivables Trust 2007-2")
    assert (
        count_structural_tokens(body, vocab) == 3
    )  # receivable, trust, and the deal digit
    assert is_variant(body, vocab)
    assert clean_key(body, vocab) == ("santander", "drive", "auto")


# --- clustering invariants ------------------------------------------------


def test_series_variants_collapse_into_one_family(index: CompanyFamilyIndex) -> None:
    """The core requirement: one trust filing per deal is still one family."""
    keys = {
        index.resolve(cik, name).family_key
        for cik, name in [
            ("0001383094", "Santander Drive Auto Receivables LLC"),
            ("0001398244", "Santander Drive Auto Receivables Trust 2007-2"),
            ("0001570776", "Santander Drive Auto Receivables Trust 2013-2"),
            ("0001600109", "Santander Drive Auto Receivables Trust 2014-4"),
        ]
    }
    assert keys == {"santander drive"}


def test_family_representative_is_the_parent_not_a_series(
    index: CompanyFamilyIndex,
) -> None:
    assert (
        index.resolve(
            "0001398244", "Santander Drive Auto Receivables Trust 2007-2"
        ).representative_name
        == "Santander Drive Auto Receivables LLC"
    )


def test_head_aliases_merge_a_parent_and_its_series(index: CompanyFamilyIndex) -> None:
    parent = index.resolve("0000019617", "JPMorgan Chase & Co")
    series = index.resolve(
        "0001319760",
        "JPMorgan Chase Commercial Mortgage Securities Corp Series 2005-LDP3",
    )
    assert parent.family_key == series.family_key == "jpmorgan chase"


def test_morgan_stanley_resolves_to_its_parent(index: CompanyFamilyIndex) -> None:
    parent = index.resolve("0000895421", "Morgan Stanley")
    series = index.resolve(
        "0001387224", "Morgan Stanley ABS Capital I Inc. Trust 2007-HE4"
    )
    assert parent.family_key == series.family_key == "morgan stanley"
    assert parent.representative_name == "Morgan Stanley"


def test_one_shared_token_is_not_enough_to_merge(index: CompanyFamilyIndex) -> None:
    """Honda Motor and Honda Auto are different companies.

    Merging them on a single shared token would fold an automaker into its own
    finance arm and skew any quota-balanced sample.
    """
    honda_motor = index.derive_company_family("Honda Motor Co Ltd")
    honda_auto = index.resolve(
        "0001566138", "Honda Auto Receivables 2013-1 Owner Trust"
    )
    assert honda_motor == "honda motor"
    assert honda_auto.family_key == "honda auto"
    assert honda_motor != honda_auto.family_key


def test_short_operating_companies_keep_their_own_identity(
    index: CompanyFamilyIndex,
) -> None:
    assert index.resolve("0000866787").family_key == "autozone"
    assert index.derive_company_family("Auto Zone Co Ltd") == "auto zone"
    assert index.derive_company_family("Mortgage One LLC") == "mortgage one"


def test_variant_flag_distinguishes_series_from_parent(
    index: CompanyFamilyIndex,
) -> None:
    assert index.resolve("0001398244").is_variant is True
    assert index.resolve("0000019617").is_variant is False


def test_family_ids_are_stable_and_key_derived() -> None:
    assert family_id_for("santander drive") == family_id_for("santander  drive")
    assert family_id_for("santander drive") != family_id_for("honda auto")
    assert len(family_id_for("santander drive")) == 12


def test_every_resolved_member_shares_its_family_id(
    index: CompanyFamilyIndex, corpus: list[tuple[str, str]]
) -> None:
    santander = [
        index.resolve(cik, name) for cik, name in corpus if "Santander" in name
    ]
    assert len({i.family_id for i in santander}) == 1
    assert len({i.family_key for i in santander}) == 1


# --- resolution behaviour -------------------------------------------------


def test_resolve_accepts_padded_and_unpadded_ciks(index: CompanyFamilyIndex) -> None:
    padded = index.resolve("0000019617")
    bare = index.resolve("19617")
    assert padded.family_id == bare.family_id


def test_resolve_falls_back_to_stateless_derivation(index: CompanyFamilyIndex) -> None:
    """A registrant absent from the seed must still resolve to something."""
    info = index.resolve("9999999999", "Totally Unknown Widgets Inc")
    assert info.family_key
    assert info.family_id
    assert info.is_variant is False


def test_resolve_by_name_when_the_cik_is_unknown(index: CompanyFamilyIndex) -> None:
    by_name = index.resolve("9999999999", "AutoZone Inc")
    assert by_name.family_key == "autozone"


def test_stateless_deriver_with_an_explicit_vocabulary() -> None:
    empty = CompanyFamilyIndex(
        structural_vocab={"trust", "series", "receivable"},
        cik_to_info={},
        name_to_info={},
    )
    assert (
        empty.derive_company_family("Santander Drive Auto Receivables Trust 2020-1")
        == "santander drive"
    )


def test_deriver_handles_empty_input(index: CompanyFamilyIndex) -> None:
    assert index.derive_company_family("") == ""


def test_index_is_immutable_after_construction(corpus: list[tuple[str, str]]) -> None:
    built = CompanyFamilyIndex.build_from_records(corpus)
    with pytest.raises(TypeError):
        built._cik_to_info["x"] = CompanyFamilyInfo("", "", "", "", "", False)  # type: ignore[index]


# --- factories ------------------------------------------------------------


def _write_profiles(path: Path, rows: list[tuple[str, str]]) -> Path:
    """Write a minimal ``company_profiles.parquet``-shaped corpus."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    schema = pa.schema(
        [
            ("cik", pa.string()),
            ("identity", pa.struct([("name", pa.string())])),
        ]
    )
    table = pa.Table.from_pylist(
        [{"cik": cik, "identity": {"name": name}} for cik, name in rows],
        schema=schema,
    )
    pq.write_table(table, path)
    return path


def test_from_existing_profiles_derives_families_from_the_profile_corpus(
    tmp_path: Path, corpus: list[tuple[str, str]]
) -> None:
    built = CompanyFamilyIndex.from_existing_profiles(
        _write_profiles(tmp_path / "p.parquet", corpus)
    )
    assert len(built) == len(corpus)
    assert built.resolve("0001398244").family_key == "santander drive"


def test_from_existing_profiles_normalizes_unpadded_ciks(
    tmp_path: Path, corpus: list[tuple[str, str]]
) -> None:
    built = CompanyFamilyIndex.from_existing_profiles(
        _write_profiles(tmp_path / "p.parquet", corpus)
    )
    assert built.resolve("0000019617").family_id == built.resolve("19617").family_id


def test_from_existing_profiles_skips_profiles_without_a_name(tmp_path: Path) -> None:
    profiles = _write_profiles(
        tmp_path / "p.parquet",
        [
            ("0000000001", "GOOD COMPANY INC"),
            ("0000000002", ""),
            ("", "NO CIK INC"),
        ],
    )
    assert len(CompanyFamilyIndex.from_existing_profiles(profiles)) == 1


def test_from_existing_profiles_reads_a_materialized_catalog(
    tmp_path: Path, sample_source: Path
) -> None:
    from edgar_sec.pipelines.filing_catalog.catalog_job import materialize
    from edgar_sec.pipelines.filing_catalog.paths import resolve_filing_catalog_paths

    root = tmp_path / "art"
    manifest = materialize(sample_source, root)
    profiles = resolve_filing_catalog_paths(root).snapshot_profiles_file(
        str(manifest["catalog_id"])
    )
    built = CompanyFamilyIndex.from_existing_profiles(profiles)
    assert len(built) > 0
    assert built.resolve("0000320193").family_key == "apple fixture"


def test_from_existing_profiles_reports_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="company profiles file not found"):
        CompanyFamilyIndex.from_existing_profiles(tmp_path / "absent.parquet")


# --- determinism ----------------------------------------------------------


def test_building_twice_gives_identical_results(corpus: list[tuple[str, str]]) -> None:
    first = CompanyFamilyIndex.build_from_records(corpus)
    second = CompanyFamilyIndex.build_from_records(list(reversed(corpus)))
    for cik, _ in corpus:
        assert first.resolve(cik) == second.resolve(cik), cik


def test_a_fixed_profile_corpus_gives_byte_stable_family_ids(
    tmp_path: Path, corpus: list[tuple[str, str]]
) -> None:
    profiles = _write_profiles(tmp_path / "p.parquet", corpus)
    first = CompanyFamilyIndex.from_existing_profiles(profiles)
    second = CompanyFamilyIndex.from_existing_profiles(profiles)
    for cik, info in first.cik_to_info.items():
        assert second.cik_to_info[cik].family_id == info.family_id, cik


def test_derived_family_keys_match_the_inline_corpus() -> None:
    inline: list[tuple[str, Any]] = [
        ("0001383094", "Santander Drive Auto Receivables LLC"),
        ("0001398244", "Santander Drive Auto Receivables Trust 2007-2"),
        ("0001570776", "Santander Drive Auto Receivables Trust 2013-2"),
        ("0001600109", "Santander Drive Auto Receivables Trust 2014-4"),
        ("0000019617", "JPMorgan Chase & Co"),
        (
            "0001319760",
            "JPMorgan Chase Commercial Mortgage Securities Corp Series 2005-LDP3",
        ),
        ("0000895421", "Morgan Stanley"),
        ("0001387224", "Morgan Stanley ABS Capital I Inc. Trust 2007-HE4"),
        ("0001566138", "Honda Auto Receivables 2013-1 Owner Trust"),
        ("0000866787", "AutoZone Inc"),
    ]
    built = CompanyFamilyIndex.build_from_records(inline)
    assert built.resolve("0001398244").family_key == "santander drive"


def test_cik_to_info_is_read_only(corpus: list[tuple[str, str]]) -> None:
    built = CompanyFamilyIndex.build_from_records(corpus)
    with pytest.raises(TypeError):
        built.cik_to_info["x"] = CompanyFamilyInfo("", "", "", "", "", False)
