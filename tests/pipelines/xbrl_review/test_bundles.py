"""Tests for XBRL review corpus-bundle resolution and loading."""

import json
from pathlib import Path

import pytest

from edgar_sec.engine.xbrl.discovery.cohort import (
    canonical_probe_cohort_path,
    canonical_seed_cohort_path,
    canonical_sp100_cohort_path,
    canonical_vintage_cohort_path,
    load_canonical_union_cohort,
)
from edgar_sec.pipelines.xbrl_review.bundles import (
    BundleNotFoundError,
    bundle_dir_for,
    bundle_root,
    corpus_registry_path,
    load_filing,
    missing_bundles,
    registry_filings,
)


def test_registry_filings_cover_canonical_registry() -> None:
    """Verify the canonical seed registry loads in full."""
    filings = registry_filings()
    assert len(filings) == 49
    assert len({str(f.accession) for f in filings}) == 49


def test_registry_filings_with_vintage_registry_path() -> None:
    """Verify a registry path loads that dataset's registry instead."""
    filings = registry_filings(registry_path=canonical_vintage_cohort_path())
    assert len(filings) == 16
    assert {f.firm for f in filings} == {"BAC", "MSFT", "AAPL", "SHEL", "BP", "NVS"}


def test_registry_filings_with_sp100_registry_path() -> None:
    """Verify a registry path loads the SP100 scale corpus instead."""
    filings = registry_filings(registry_path=canonical_sp100_cohort_path())
    assert len(filings) == 60
    assert len({f.firm for f in filings}) == 60
    assert {"MA", "ARM", "AZN", "BABA"} <= {f.firm for f in filings}


def test_every_registry_accession_has_a_bundle() -> None:
    """Verify no registry filing is missing its corpus bundle."""
    accessions = [str(f.accession) for f in load_canonical_union_cohort()]
    assert missing_bundles(accessions) == []


def test_corpus_registry_path_recognizes_only_corpus_registries(
    tmp_path: Path,
) -> None:
    """Verify a source ref selects a corpus only with its source registry."""
    assert corpus_registry_path(str(canonical_seed_cohort_path())) == (
        canonical_seed_cohort_path()
    )
    assert corpus_registry_path(str(canonical_vintage_cohort_path())) == (
        canonical_vintage_cohort_path()
    )
    assert corpus_registry_path(str(canonical_sp100_cohort_path())) == (
        canonical_sp100_cohort_path()
    )
    assert corpus_registry_path(str(canonical_probe_cohort_path())) == (
        canonical_probe_cohort_path()
    )
    assert corpus_registry_path(None) is None
    plain = tmp_path / "dataset.json"
    plain.write_text("[]", encoding="utf-8")
    assert corpus_registry_path(str(plain)) is None


def test_bundle_dir_for_vintage_accession_resolves_vintage_root() -> None:
    """Verify BAC 2011 resolves from the vintage corpus (cross-corpus pair)."""
    bundle_dir = bundle_dir_for("0000070858-12-000155")
    assert bundle_dir.parent.name == "vintage"
    assert bundle_dir.name == "bac_2011_10k"


def test_bundle_dir_for_restricted_to_wrong_corpus_refuses() -> None:
    """Verify a registry path restricts resolution to its own corpus."""
    with pytest.raises(BundleNotFoundError):
        bundle_dir_for(
            "0000070858-12-000155", registry_path=canonical_seed_cohort_path()
        )


def test_bundle_dir_for_sp100_accession_resolves_sp100_root() -> None:
    """Verify MA 2024 resolves from the SP100 corpus root."""
    bundle_dir = bundle_dir_for("0001141391-25-000011")
    assert bundle_dir.parent.name == "sp100"
    assert bundle_dir.name == "ma_2024_10k"


def test_bundle_dir_for_sp100_restricted_to_seed_refuses() -> None:
    """Verify an SP100 accession refuses under the seed registry alone."""
    with pytest.raises(BundleNotFoundError):
        bundle_dir_for(
            "0001141391-25-000011", registry_path=canonical_seed_cohort_path()
        )


def test_bundle_dir_for_unknown_accession_refuses() -> None:
    """Verify an unregistered accession is a refusal, not an empty bundle."""
    with pytest.raises(BundleNotFoundError):
        bundle_dir_for("0000000000-25-000001")


def test_load_filing_reads_vintage_bundle() -> None:
    """Verify a vintage filing loads through the same bundle path."""
    bac_2011 = next(
        f
        for f in registry_filings(registry_path=canonical_vintage_cohort_path())
        if f.fy == 2011
    )
    loaded = load_filing(bac_2011)
    assert len(loaded.facts) > 1000
    assert loaded.bundle_dir.parent.name == "vintage"


def test_registry_filings_with_probe_registry_path() -> None:
    """Verify a registry path loads the cross-form probe corpus instead."""
    filings = registry_filings(registry_path=canonical_probe_cohort_path())
    assert len(filings) == 445
    assert len({str(f.accession) for f in filings}) == 445
    forms = [f.form for f in filings]
    assert forms.count("10-Q") == 11
    assert forms.count("10-Q/A") == 1
    assert forms.count("10-K") == 2
    assert forms.count("10-K/A") == 2
    assert forms.count("8-K") == 7
    assert forms.count("8-K/A") == 2
    assert forms.count("6-K") == 11
    assert forms.count("20-F") == 5
    assert forms.count("40-F") == 20
    assert forms.count("DEF 14A") == 12
    assert forms.count("SD") == 180
    assert forms.count("S-1") == 4
    assert forms.count("S-4") == 4
    assert forms.count("F-1") == 15
    assert forms.count("11-K") == 15
    assert forms.count("N-CSR") == 14
    assert forms.count("N-CSRS") == 14
    assert forms.count("424B2") == 1
    assert forms.count("424B3") == 1
    assert forms.count("424B5") == 1
    assert forms.count("424B7") == 1
    assert forms.count("424B8") == 1
    assert forms.count("S-8") == 1
    assert forms.count("S-3") == 1
    assert forms.count("F-3") == 1
    assert forms.count("10-KT") == 6
    assert forms.count("10-KT/A") == 1
    assert forms.count("10-QT") == 2
    assert {f.firm for f in filings} == {
        "MSFT",
        "AAPL",
        "JPM",
        "CAT",
        "AMZN",
        "ALK",
        "YYAI",
        "TSN",
        "C",
        "ADM",
        "KD",
        "NEE",
        "ITW",
        "FTS",
        "HSBC",
        "MCD",
        "PJT",
        "MTX",
        "WHK",
        "VISK",
        "MRM",
        "ABT",
        "GDV",
        "OXLC",
        "ISHARES",
        "STARWOOD",
        "HomeTrust",
        "L3Harris",
        "Myriad",
        "RoyalGold",
        "InspireMD",
        "ESG",
        "Dawson",
        "PLD",
        "BAC",
        "COIN",
        "UBS",
        "MFG",
        "DB",
        "RY",
        "DBVT",
        "CVE",
        "DSGX",
        "INTR",
        "NTR",
        "ABB",
        "ASX",
        "ARCO",
        "MOGU",
        "GROY",
        "TAC",
        "TRI",
        "NMG",
        "DOLE",
        "NVGS",
        "GLXY",
        "CLDI",
        "MOBQ",
        "HLT",
        "TCBX",
        "UTZ",
        "XP",
        "GENI",
        "PBM",
        "R",
        "KEY",
        "DUK",
        "PTY",
        "GDL",
        "TY",
        "STK",
        "UA",
        "BSRR",
        "RLJ",
        "NREF",
        "SPST",
        "ICE8496",
        "SOUTHWES4844",
        "ITMSF",
        "DTCC4958",
        "TU",
        "HELP",
        "BAM",
        "CCJ",
        "GLDM",
        "DBE",
        "UGA",
        "PLTM",
        "JOSS7746",
        "JAN",
        "PIA0169",
        "PRUCO1313",
        "PROTECTI8923",
        "Decision5611",
        "OSTX",
        "MENS",
        "Chromari8383",
        "AMERICAN5138",
        "SOUTHWES2487",
        "VIRGINIA3682",
        "DTE8385",
        "Barclays2111",
        "Wells7898",
        "DCBO",
        "NATIONWI3905",
        "JNL3691",
        "Axxes8365",
        "Apollo7532",
        "Apollo7634",
        "iSHARES0663",
        "VanEck7360",
        "RBC2950",
        "Capitol7551",
        "Mutual0695",
        "Brookfie0738",
        "COLUMBIA5425",
        "CERES7396",
        "GSG",
        "TENGION6391",
        "LINCOLN0739",
        "Broadmar4797",
        "Arch7561",
        "ALMU",
        "ZEO",
        "BMY",
        "YmAbs2964",
        "RIDGEFIE2152",
        "Blacksto3498",
        "YEXT",
        "AGQ",
        "COLD",
        "Shapell9377",
        "SPRINT1830",
        "CASK",
        "MSIF",
        "OIA",
        "MAIN",
        "FT7009",
        "ECC",
        "FT2050",
        "FT7048",
        "ANIP",
        "ILG4620",
        "Panasoni3271",
        "WINV",
        "Fibrocel7097",
        "Flat2078",
        "BMO1132",
        "Privacor7579",
        "NMZ",
        "Goldman0145",
        "FT4224",
        "Horizons1030",
        "Calamos3291",
        "AIRI",
        "Rocky0869",
        "GTLL",
        "Stratos1517",
        "STAG",
        "CatchMar1141",
        "AMERICAN4543",
        "CONDOR9545",
        "3D6753",
        "ACTIVECA9896",
        "SEPARATE4486",
        "FT9702",
        "Equitabl2818",
        "EMARINE8377",
        "HBNC",
        "TVTX",
        "PNC8823",
        "SILVERCO0677",
        "EXXONMOB4088",
        "CHEVRONC3410",
        "BPPLC3807",
        "EOGRESOU1189",
        "FREEPORT1259",
        "ALBEMARL5913",
        "MINERALS1014",
        "CONOCOPH3165",
        "NEWMONTC4727",
        "SHELLPLC6965",
        "NUTRIENL5964",
        "NEXTERAE3308",
        "CENOVUSE5260",
        "NOUVEAUM9752",
        "CHENIERE3570",
        "HALLIBUR5012",
        "IMPERIAL9938",
        "ALLETEIN6756",
        "MARATHON1778",
        "WILLIAMS7263",
        "COEURMIN5466",
        "MURPHYOI7423",
        "CLEVELAN4065",
        "PANAMERI1992",
        "VISTAGOL3324",
        "OCCIDENT7468",
        "NEWGOLDI0166",
        "COTERRAE8470",
        "GRANITEC1459",
        "EXPANDEN5126",
        "CHEMICAL9037",
        "ELDORADO8608",
        "SSRMININ1638",
        "BHPGROUP1809",
        "LITHIUMA6983",
        "OBSIDIAN4388",
        "TECKRESO6986",
        "MARTINMA6076",
        "OVINTIVI2580",
        "HECLAMIN9413",
        "ALCOACOR5149",
        "DEVONENE0012",
        "RANGERES5852",
        "EAGLEMAT8646",
        "CANADIAN7413",
        "DRDGOLDL3512",
        "SEMPRA2208",
        "ONEOKINC9684",
        "SILVERCR9520",
        "TREKORME8518",
        "LARGOINC0438",
        "FIRSTMAJ8648",
        "ENDEAVOU7866",
        "ENERGYFU5849",
        "LONCORGO2619",
        "EQUINOXG6607",
        "HUDBAYMI2422",
        "INTEGRAR2387",
        "GALIANOG7757",
        "IGOLDCOR3962",
        "SLBLIMIT7347",
        "RIOTINTO3064",
        "SMENERGY3538",
        "VAALCOEN4627",
        "ENTERPRI1219",
        "NEXGENEN8535",
        "LITHIUMA0972",
        "LIONCOPP9688",
        "AMERICAS6973",
        "PEABODYE4728",
        "MEXICANP2782",
        "MAKOMINI4930",
        "NORTHERN4485",
        "NEWPACIF9085",
        "URENERGY5205",
        "VERMILIO3135",
        "FERROGLO9877",
        "OSISKOGO1852",
        "EQTCORP3213",
        "FRANCONE6346",
        "AGNICOEA2809",
        "MCEWENIN4203",
        "PERPETUA6243",
        "BGOLDCOR9937",
        "DESCARTE0140",
        "TRANSALT4800",
        "ROYALBAN0275",
        "MINDWALK5925",
        "GOLDRESE2725",
        "BURCONNU8399",
        "ELECTRAB7184",
        "IMCANNAB2030",
        "THOMSONR5124",
        "HIVEDIGI0424",
        "ILLUMINH1233",
        "AIRPRODU2969",
        "AMERICAN4904",
        "AMERICAN4962",
        "HRBLOCKI2659",
        "ARCHERDA7084",
        "MOOGINC7887",
        "BRISTOLM4272",
        "NIKEINC0187",
        "CATERPIL8230",
        "KEYTRONI9733",
        "AMERICAN5272",
        "BECTONDI0795",
        "ABRDNINC3290",
        "JPMORGAN9617",
        "INTELCOR0863",
        "INVETECH6044",
        "GENERALE0545",
        "TRICONTI9614",
        "PIMCOCOR0935",
        "ABRDNWOR5977",
        "ABRDNEME6676",
        "COLUMBIA1420",
        "OXFORDLA5222",
        "HIGHLAND2148",
        "GREENPOW4547",
        "PSYENCEB5062",
        "CHINANAT3628",
        "COREAIHO9009",
        "MEDIROMH9704",
        "ARQITQUA9690",
        "DEFSECTE9823",
        "BBBFOODS8954",
        "REZOLVEA0294",
        "HEIDMARM9471",
        "ASIAPACI6980",
        "ABRDNGLO0195",
        "EAGLEPOI4174",
        "ARROWMAR8987",
        "SOURCECA1847",
        "ABERDEEN7100",
        "JOHNHANC9828",
        "JOHNHANC5886",
        "JOHNHANC5683",
        "CALAMOSC2719",
        "CALAMOSC1471",
    }


def test_probe_registry_source_folder_bijection() -> None:
    """Verify probe registry, source registry, and folders correspond 1:1."""
    registry_path = canonical_probe_cohort_path()
    filings = registry_filings(registry_path=registry_path)
    root = bundle_root(registry_path)
    payload = json.loads(
        (root / "fixture_source_registry.json").read_text(encoding="utf-8")
    )
    sources = payload["bundles"]
    assert {str(f.accession) for f in filings} == {
        s["cohort_accession"] for s in sources
    }
    assert {s["folder"] for s in sources} == {
        p.name for p in root.iterdir() if p.is_dir()
    }
    for source in sources:
        assert source["source_accession"] == source["cohort_accession"]
        assert source["source_matches_cohort"] is True
        assert source["provenance_status"] == "VERIFIED"
        assert (root / source["folder"] / "facts.parquet").is_file()


def test_bundle_dir_for_probe_accession_resolves_probe_root() -> None:
    """Verify a probe 10-Q accession resolves from the probe corpus root."""
    bundle_dir = bundle_dir_for("0001193125-26-436133")
    assert bundle_dir.parent.name == "probe"
    assert bundle_dir.name == "msft_2026_10q"


def test_bundle_dir_for_probe_restricted_to_seed_refuses() -> None:
    """Verify a probe accession refuses under the seed registry alone."""
    with pytest.raises(BundleNotFoundError):
        bundle_dir_for(
            "0001193125-26-436133", registry_path=canonical_seed_cohort_path()
        )


def test_load_filing_reads_probe_bundle() -> None:
    """Verify a probe 10-Q loads through the same bundle path."""
    msft_q = next(
        f
        for f in registry_filings(registry_path=canonical_probe_cohort_path())
        if f.firm == "MSFT" and f.form == "10-Q"
    )
    loaded = load_filing(msft_q, registry_path=canonical_probe_cohort_path())
    assert len(loaded.facts) > 1000
    assert loaded.bundle_dir.parent.name == "probe"


def test_load_filing_reads_bundle_artefacts() -> None:
    """Verify one filing loads facts, arcs, and declarations."""
    mcd = next(f for f in registry_filings() if f.firm == "MCD")
    loaded = load_filing(mcd)
    assert len(loaded.facts) > 1000
    assert len(loaded.calc_arcs) > 100
    assert len(loaded.pres_arcs) > 100
    assert {arc.parent_qname for arc in loaded.pres_arcs}
    assert "us-gaap:CashAndCashEquivalentsAtCarryingValue" in loaded.declarations
    assert loaded.cohort_entry.accession == str(mcd.accession)
    assert loaded.cohort_entry.facts_path.is_file()
