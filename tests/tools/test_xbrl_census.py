"""Tests for the scored census runner and its faithful replay."""

from pathlib import Path

from edgar_sec.engine.xbrl.review.benchmark import summarize_census
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.engine.xbrl.solve.tokenizer import ConceptTokenizer
from edgar_sec.tools.xbrl_census import classify, replay_faithful, run_population


def _rec(status: str, value: float | None = None, candidates=()) -> dict:
    """One recorded scope result in the census record shape."""
    return {
        "status": status,
        "value": value,
        "candidates": list(candidates),
        "tier": "",
        "reported_qname": None,
        "equivalents": [],
        "scope": {
            "start": "2024-01-01",
            "end": "2024-12-31",
            "instant": None,
            "unit": None,
            "span": 365,
            "kind": "duration",
        },
    }


def test_replay_prefers_conflict_over_ambiguous_within_a_tier() -> None:
    """The split precedence: a faithful tier's CONFLICT outranks its AMBIGUOUS."""
    records = [_rec("AMBIGUOUS"), _rec("CONFLICT", value=-5.0)]
    faithful = replay_faithful(records, ())
    assert faithful is not None
    assert faithful["status"] == "CONFLICT"
    facade = _rec("CONFLICT", value=-5.0)
    assert classify(facade, faithful) == "honest-faithful"


def test_replay_keeps_verified_above_conflict() -> None:
    """VERIFIED stays on top of the split precedence inside a tier."""
    records = [_rec("CONFLICT", value=-5.0), _rec("VERIFIED", value=7.0)]
    faithful = replay_faithful(records, ())
    assert faithful is not None
    assert faithful["status"] == "VERIFIED"
    assert classify(_rec("VERIFIED", value=7.0), faithful) == "correct"


def test_replay_duration_success_is_final() -> None:
    """A duration-tier success ends the replay; instants are not consulted."""
    records = [_rec("REPORTED", value=3.0), _rec("UNAVAILABLE")]
    faithful = replay_faithful(records, ())
    assert faithful is not None
    assert faithful["status"] == "REPORTED"


def test_classify_adverse_shapes() -> None:
    """Success/failure disagreements classify into the adverse classes."""
    faithful = _rec("REPORTED", value=3.0)
    assert classify(_rec("UNAVAILABLE"), faithful) == "refused"
    assert classify(_rec("REPORTED", value=4.0), faithful) == "wrong-value"
    honest = _rec("AMBIGUOUS")
    assert classify(_rec("REPORTED", value=1.0), honest) == "wrong-span"


def test_corpus_cohort_entries_resolve_both_bac_filings() -> None:
    """Cohort entries key by accession: BAC resolves to eight corpus bundles."""
    from edgar_sec.tools.xbrl_census_corpus import corpus_cohort_entries

    entries = corpus_cohort_entries()
    assert len(entries) == 65
    bac = [entry for entry in entries if entry.firm == "BAC"]
    assert {str(entry.accession) for entry in bac} == {
        "0000070858-25-000139",
        "0000070858-12-000155",
        "0000070858-14-000012",
        "0000070858-16-000137",
        "0000070858-18-000009",
        "0000070858-20-000011",
        "0000070858-22-000062",
        "0000070858-24-000122",
    }
    assert {entry.facts_path.parent.name for entry in bac} == {
        "bac_2024_10k",
        "bac_2011_10k",
        "bac_2013_10k",
        "bac_2015_10k",
        "bac_2017_10k",
        "bac_2019_10k",
        "bac_2021_10k",
        "bac_2023_10k",
    }


def test_battery_gate_baseline() -> None:
    """Pin the battery baseline: 188/188 since the F7 calc fix."""
    from edgar_sec.tools.xbrl_census import run_battery_gate

    report = run_battery_gate()
    assert report.total == 188
    assert report.passed == 188
    assert report.failures == ()


def test_corpus_bundles_have_no_semantic_duplicate_facts() -> None:
    """No corpus bundle carries two facts identical except in decimals."""
    import pyarrow.parquet as pq

    from edgar_sec.tools.xbrl_census_corpus import corpus_cohort_entries

    identity_columns = (
        "accession",
        "concept_qname",
        "numeric_value",
        "text_value",
        "unit",
        "period_type",
        "start_date",
        "end_date",
        "instant_date",
        "dimensions_json",
        "context_id",
    )
    entries = corpus_cohort_entries()
    assert len(entries) == 65
    duplicates = []
    for entry in entries:
        rows = pq.read_table(entry.facts_path).to_pylist()
        seen = set()
        for row in rows:
            key = tuple(row[column] for column in identity_columns)
            if key in seen:
                duplicates.append((entry.facts_path.parent.name, row["concept_qname"]))
            seen.add(key)
    assert duplicates == []


def test_probe_population_single_firm_smoke(tmp_path: Path) -> None:
    """MSFT probe battery: 19 correct, 5 honest, one surfaced CONFLICT."""
    taxonomy = load_domain_taxonomy()
    tokenizer = ConceptTokenizer(taxonomy)
    evaluations = run_population("probe", ["msft"], taxonomy, tokenizer, tmp_path)
    assert len(evaluations) == 24
    summary = summarize_census(evaluations)["populations"]["probe"]
    assert summary["classification"] == {"correct": 19, "honest-faithful": 5}
    assert summary["replay_mismatches"] == 0
    assert len(summary["surfaced_conflicts"]) == 1
    assert summary["derived_artefacts"] == []
    assert summary["near_guard_violations"] == []


def test_corpus_registries_partition_the_grounded_corpus() -> None:
    """Seed and vintage registries partition the 65 grounded bundles."""
    import json

    from tests.support import fixture_path

    def rows(name: str) -> list[dict]:
        return json.loads(fixture_path(f"xbrl/{name}").read_text(encoding="utf-8"))

    def sources(corpus: str) -> list[dict]:
        payload = json.loads(
            fixture_path(f"xbrl/{corpus}/fixture_source_registry.json").read_text(
                encoding="utf-8"
            )
        )
        return payload["bundles"]

    seed_rows, vintage_rows = rows("seed_cohort.json"), rows("vintage_cohort.json")
    assert len(seed_rows) == 49
    assert len({row["firm"] for row in seed_rows}) == 49
    assert len(vintage_rows) == 16
    seed_accessions = {row["accession"] for row in seed_rows}
    vintage_accessions = {row["accession"] for row in vintage_rows}
    assert seed_accessions.isdisjoint(vintage_accessions)
    assert len(seed_accessions | vintage_accessions) == 65
    for corpus, registry_rows in (
        ("seed", seed_rows),
        ("vintage", vintage_rows),
    ):
        corpus_sources = sources(corpus)
        assert {row["accession"] for row in registry_rows} == {
            row["cohort_accession"] for row in corpus_sources
        }
        folders_on_disk = {
            path.name
            for path in fixture_path(f"xbrl/{corpus}").iterdir()
            if path.is_dir()
        }
        assert folders_on_disk == {row["folder"] for row in corpus_sources}


def test_sp100_registry_partitions_its_corpus() -> None:
    """SP100 registry, source rows, and bundle folders are in bijection."""
    import json

    from tests.support import fixture_path

    def rows(name: str) -> list[dict]:
        return json.loads(fixture_path(f"xbrl/{name}").read_text(encoding="utf-8"))

    payload = json.loads(
        fixture_path("xbrl/sp100/fixture_source_registry.json").read_text(
            encoding="utf-8"
        )
    )
    sources = payload["bundles"]
    sp100_rows = rows("sp100_cohort.json")
    assert len(sp100_rows) == 60
    assert len({row["firm"] for row in sp100_rows}) == 60
    sp100_accessions = {row["accession"] for row in sp100_rows}
    grounded_accessions = {row["accession"] for row in rows("seed_cohort.json")}
    grounded_accessions |= {row["accession"] for row in rows("vintage_cohort.json")}
    assert sp100_accessions.isdisjoint(grounded_accessions)
    assert {row["accession"] for row in sp100_rows} == {
        row["cohort_accession"] for row in sources
    }
    folders_on_disk = {
        path.name for path in fixture_path("xbrl/sp100").iterdir() if path.is_dir()
    }
    assert folders_on_disk == {row["folder"] for row in sources}


def test_sp100_bundles_have_no_semantic_duplicate_facts() -> None:
    """No SP100 bundle carries two facts identical except in decimals."""
    import pyarrow.parquet as pq

    from tests.support import bundle_dir, corpus_source_bundles

    identity_columns = (
        "accession",
        "concept_qname",
        "numeric_value",
        "text_value",
        "unit",
        "period_type",
        "start_date",
        "end_date",
        "instant_date",
        "dimensions_json",
        "context_id",
    )
    sources = [
        row
        for row in corpus_source_bundles()
        if bundle_dir(row["folder"]).parent.name == "sp100"
    ]
    assert len(sources) == 60
    duplicates = []
    for row in sources:
        facts = pq.read_table(bundle_dir(row["folder"]) / "facts.parquet").to_pylist()
        seen = set()
        for fact in facts:
            key = tuple(fact[column] for column in identity_columns)
            if key in seen:
                duplicates.append((row["folder"], fact["concept_qname"]))
            seen.add(key)
    assert duplicates == []
