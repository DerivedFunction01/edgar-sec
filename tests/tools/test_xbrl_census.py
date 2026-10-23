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


def test_seed_cohort_entries_resolve_both_bac_filings() -> None:
    """Cohort entries key by accession: BAC resolves to two distinct bundles."""
    from edgar_sec.tools.xbrl_census_corpus import seed_cohort_entries

    entries = seed_cohort_entries()
    assert len(entries) == 42
    bac = [entry for entry in entries if entry.firm == "BAC"]
    assert {str(entry.accession) for entry in bac} == {
        "0000070858-25-000139",
        "0000070858-12-000155",
    }
    assert {entry.facts_path.parent.name for entry in bac} == {
        "bac_2024_10k",
        "bac_2011_10k",
    }


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
