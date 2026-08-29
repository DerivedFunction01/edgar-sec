from __future__ import annotations

import importlib
from pathlib import Path

import pytest

cf = importlib.import_module("phases.02_filing_extraction.core.company_family")
CompanyFamilyIndex = cf.CompanyFamilyIndex
mine_structural_vocabulary = cf.mine_structural_vocabulary
normalize_name = cf.normalize_name
post_normalize = cf.post_normalize
strip_legal_forms = cf.strip_legal_forms


def test_normalize_name_abbreviation_and_plural_expansion() -> None:
    tokens = normalize_name("J.P. Morgan Chase Commercial Mtg Sec Tr 2011-C5")
    assert "mortgage" in tokens
    assert "trust" in tokens
    assert "securities" not in tokens or "security" in tokens

    tokens2 = normalize_name("Santander Drive Auto Receivables LLC")
    assert "receivable" in tokens2


def test_mine_structural_vocabulary_protects_operating_words() -> None:
    sample_names = [
        "JPMorgan Chase Commercial Mortgage Securities Corp Series 2005-LDP3",
        "Banc of America Alternative Loan Trust 2005-11 Mortgage Pass-Through Certificates, Series 2005-11",
        "Santander Drive Auto Receivables Trust 2007-2",
        "Santander Drive Auto Receivables Trust 2013-2",
        "Morgan Stanley ABS Capital I Inc. Trust 2007-HE4",
        "Mortgage One LLC",
        "AutoZone Inc",
    ]
    vocab = mine_structural_vocabulary(sample_names, min_name_len=3, min_tail_freq=1)
    assert isinstance(vocab, set)


def test_company_family_index_clustering_and_benchmarks() -> None:
    seed_csv = Path("uploads/cik-sec.csv")
    if not seed_csv.is_file():
        pytest.skip("uploads/cik-sec.csv not present")

    index = CompanyFamilyIndex.build_from_seed(seed_csv)

    # Benchmark 1: Santander variants consolidated into single family
    sant_llc = index.resolve("0001383094", "Santander Drive Auto Receivables LLC")
    sant_07 = index.resolve(
        "0001398244", "Santander Drive Auto Receivables Trust 2007-2"
    )
    sant_13 = index.resolve(
        "0001570776", "Santander Drive Auto Receivables Trust 2013-2"
    )
    sant_14 = index.resolve(
        "0001600109", "Santander Drive Auto Receivables Trust 2014-4"
    )
    assert (
        sant_llc.family_key
        == sant_07.family_key
        == sant_13.family_key
        == sant_14.family_key
        == "santander drive"
    )
    assert sant_07.representative_name == "Santander Drive Auto Receivables Llc"

    # Benchmark 2: JPMorgan alias merged
    jpm_parent = index.resolve("0000019617", "JPMorgan Chase & Co")
    jpm_05 = index.resolve(
        "0001319760",
        "Jpmorgan Chase Commercial Mortgage Securities Corp Series 2005-Ldp3",
    )
    assert jpm_parent.family_key == jpm_05.family_key == "jpmorgan chase"

    # Benchmark 3: Honda Motor and Honda Auto remain separate (1 shared token < 2 threshold)
    honda_motor = index.derive_company_family("Honda Motor Co Ltd")
    honda_auto = index.resolve(
        "0001566138", "Honda Auto Receivables 2013-1 Owner Trust"
    )
    assert honda_motor != honda_auto.family_key
    assert honda_motor == "honda motor"
    assert honda_auto.family_key == "honda auto"

    # Benchmark 4: Morgan Stanley representative is parent
    ms_parent = index.resolve("0000895421", "Morgan Stanley")
    ms_abs = index.resolve(
        "0001387224", "Morgan Stanley ABS Capital I Inc. Trust 2007-HE4"
    )
    assert ms_parent.family_key == ms_abs.family_key == "morgan stanley"

    # Benchmark 5: Short operating companies protected
    auto_zone = index.resolve("0000866787")
    d_az = index.derive_company_family("Auto Zone Co Ltd")
    d_mo = index.derive_company_family("Mortgage One LLC")
    acme = index.resolve("0000002070", "Acme Electric Corp")
    assert auto_zone.family_key == "autozone"
    assert d_az == "auto zone"
    assert d_mo == "mortgage one"
    assert acme.family_key == "acme electric"


def test_stateless_deriver_fallback() -> None:
    index = CompanyFamilyIndex(
        structural_vocab={"trust", "series", "receivable"},
        cik_to_info={},
        name_to_info={},
    )
    res = index.derive_company_family("Santander Drive Auto Receivables Trust 2020-1")
    assert res == "santander drive"
