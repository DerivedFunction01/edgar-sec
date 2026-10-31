"""Scored census regression over the grounded XBRL seed fixtures."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.engine.xbrl.review.benchmark import (
    CENSUS_EXPECTATIONS,
    score_census,
    summarize_census,
)
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.query import QueryMode, QueryStatus
from edgar_sec.engine.xbrl.solve.scoping import FactScope
from edgar_sec.engine.xbrl.solve.tokenizer import ConceptTokenizer
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.tools.xbrl_census_corpus import (
    EXTRA_TERMS,
    PINNED_CLASS_V,
    PROBE_FIRMS,
    PROBE_TERMS,
    PROBE_TERMS_FLAT,
    SPAN_FIRMS,
    SPAN_FY,
    SPAN_RO,
    SPAN_VERIFY,
    XVA_Q,
    discovered_concepts,
    firm_fiscal_year,
    headline_revenue_qname,
    make_facade,
    make_facade_folder,
    corpus_folders,
    span_days,
    textblock_qnames,
)

REPO = Path(__file__).resolve().parents[2]
SUCCESS = {QueryStatus.REPORTED, QueryStatus.DERIVED, QueryStatus.VERIFIED}
_RANK = {
    "VERIFIED": 0,
    "REPORTED": 1,
    "CONFLICT": 2,
    "DERIVED": 3,
    "AMBIGUOUS": 4,
    "UNAVAILABLE": 5,
}


def values_equal(a: float | None, b: float | None) -> bool:
    """Relative-tolerance numeric equality; None matches only None."""
    if a is None or b is None:
        return a is b
    return abs(a - b) <= 1e-6 * max(1.0, abs(a), abs(b))


def result_record(result, scope: FactScope | None) -> dict:
    """Serialize one query result (plus its scope) for offline replay."""
    rec = {
        "status": str(result.status),
        "value": result.value,
        "candidates": list(result.candidate_qnames),
        "tier": result.tier,
        "reported_qname": (
            result.reported_fact.concept_qname if result.reported_fact else None
        ),
        "equivalents": [
            {
                "qname": e.qname,
                "tier": e.tier,
                "via_default": e.via_default,
                "distance": e.modifier_distance,
            }
            for e in result.equivalents
        ],
    }
    if scope is not None:
        rec["scope"] = {
            "start": scope.start_date,
            "end": scope.end_date,
            "instant": scope.instant_date,
            "unit": scope.unit,
            "span": span_days(scope.start_date, scope.end_date),
            "kind": "instant" if scope.instant_date else "duration",
        }
    if str(result.status) == "CONFLICT":
        rec["candidate_facts"] = [
            {
                "qname": f.concept_qname,
                "value": f.value if isinstance(f.value, (int, float)) else None,
                "decimals": f.decimals,
                "unit": f.unit,
                "start": f.start_date,
                "end": f.end_date,
                "instant": f.instant_date,
                "dimensions": f.dimensions,
            }
            for f in result.candidate_facts
        ]
    return rec


def group_key(scope_rec: dict) -> tuple:
    """The faithful-tier group a scope record belongs to."""
    s = scope_rec["scope"]
    if s["kind"] == "instant":
        return ("instant", s["instant"])
    return ("duration", s["start"], s["end"])


def tier_outcome(records: list[dict]) -> dict | None:
    """The tier's outcome under the facade's split precedence.

    VERIFIED > REPORTED > CONFLICT > DERIVED > AMBIGUOUS > UNAVAILABLE;
    ties keep scope order, mirroring the fiscal tier outcome.
    """
    best = None
    for rec in records:
        if best is None or _RANK[rec["status"]] < _RANK[best["status"]]:
            best = rec
    return best


def replay_faithful(records: list[dict], facts: tuple[XbrlFact, ...]) -> dict | None:
    """R1-strict faithful outcome over recorded scopes; never reimplements the engine."""
    groups: dict[tuple, list[dict]] = {}
    for rec in records:
        groups.setdefault(group_key(rec), []).append(rec)
    dur_spans = {
        key: span_days(key[1], key[2]) for key in groups if key[0] == "duration"
    }
    t1_key = max(dur_spans, key=lambda k: dur_spans[k]) if dur_spans else None
    instant_counts: Counter = Counter()
    for fact in facts:
        if not fact.dimensions and fact.period_type == "instant" and fact.instant_date:
            instant_counts[fact.instant_date] += 1
    t1 = groups.get(t1_key, []) if t1_key else []
    t1_outcome = tier_outcome(t1)
    if t1_outcome is not None and t1_outcome["status"] in {str(s) for s in SUCCESS}:
        return t1_outcome
    if t1_outcome is not None and t1_outcome["status"] != "UNAVAILABLE":
        qnames = {q for rec in t1 for q in rec["candidates"]}
        has_duration = any(
            f.concept_qname in qnames and f.period_type == "duration" for f in facts
        )
        if has_duration:
            return t1_outcome
    fy_instants = [key for key in groups if key[0] == "instant"]
    t2_outcome = None
    if fy_instants:
        modal = max(
            fy_instants,
            key=lambda k: (instant_counts.get(k[1], 0), k[1]),
        )
        t2_outcome = tier_outcome(groups[modal])
    if t1_outcome is not None and t1_outcome["status"] != "UNAVAILABLE":
        return t2_outcome if t2_outcome is not None else t1_outcome
    if t2_outcome is not None and t2_outcome["status"] != "UNAVAILABLE":
        return t2_outcome
    return records[0] if records else None


def classify(facade: dict, faithful: dict | None) -> str:
    """Classify a facade outcome against its faithful-tier replay."""
    if faithful is None:
        return "unfaithful non-answer"
    f_ok = facade["status"] in {str(s) for s in SUCCESS}
    t_ok = faithful["status"] in {str(s) for s in SUCCESS}
    if t_ok:
        if not f_ok:
            return "refused"
        if facade["status"] == faithful["status"] and values_equal(
            facade["value"], faithful["value"]
        ):
            return "correct"
        return "wrong-value"
    if f_ok:
        return "wrong-span"
    if facade["status"] == faithful["status"]:
        if (
            values_equal(facade["value"], faithful["value"])
            and facade["candidates"] == faithful["candidates"]
        ):
            return "honest-faithful"
        return "unfaithful non-answer"
    return "unfaithful non-answer"


def tolerance(fact: dict) -> float:
    """Rounding-interval half-width implied by a fact's stated decimals."""
    if fact["decimals"] is None:
        return 0.0001
    return 0.5 * (10.0 ** (-fact["decimals"]))


def intervals_consistent(facts: list[dict]) -> bool:
    """True iff all numeric values form one rounding-interval cluster."""
    intervals = sorted(
        (f["value"] - tolerance(f), f["value"] + tolerance(f))
        for f in facts
        if f["value"] is not None
    )
    low = high = None
    for lo, hi in intervals:
        if low is None:
            low, high = lo, hi
        elif lo <= high and hi >= low:
            low, high = max(low, lo), min(high, hi)
        else:
            return False
    return True


def conflict_is_precision_duplicate(rec: dict) -> bool | None:
    """Adjudicate a CONFLICT record's candidate facts (register A)."""
    facts = rec.get("candidate_facts")
    if not facts:
        return None
    by_context: dict[tuple, list[dict]] = {}
    for f in facts:
        key = (
            f["unit"],
            f["start"],
            f["end"],
            f["instant"],
            json.dumps(f["dimensions"], sort_keys=True),
        )
        by_context.setdefault(key, []).append(f)
    multi = [fs for fs in by_context.values() if len({f["value"] for f in fs}) > 1]
    if not multi:
        return None
    return all(intervals_consistent(fs) for fs in multi)


def attribute(facade: dict, records: list[dict]) -> dict | None:
    """First recorded scope whose (status, value, candidates) match the facade's."""
    for rec in records:
        if (
            rec["status"] == facade["status"]
            and values_equal(rec["value"], facade["value"])
            and rec["candidates"] == facade["candidates"]
        ):
            return rec
    for rec in records:
        if rec["status"] == facade["status"] and values_equal(
            rec["value"], facade["value"]
        ):
            return rec
    return None


def scope_matches(fact: XbrlFact, scope: dict) -> bool:
    """True when an undimensioned fact sits inside the recorded scope."""
    if fact.dimensions:
        return False
    if scope["kind"] == "instant":
        return fact.period_type == "instant" and fact.instant_date == scope["instant"]
    return (
        fact.period_type == "duration"
        and fact.start_date == scope["start"]
        and fact.end_date == scope["end"]
    )


def near_guard_violation(facade_rec: dict, attributed: dict | None, facts) -> bool:
    """Independent Step 5 guard check: divergent values inside the best tier group."""
    if attributed is None:
        return False
    best = facade_rec["equivalents"][0]
    group = [
        e
        for e in facade_rec["equivalents"]
        if (e["tier"], e["via_default"]) == (best["tier"], best["via_default"])
    ]
    if len(group) <= 1:
        return False
    per_qname: dict[str, list[dict]] = {}
    for e in group:
        vals = [
            {"value": float(f.value), "decimals": f.decimals}
            for f in facts
            if f.concept_qname == e["qname"]
            and scope_matches(f, attributed["scope"])
            and (
                attributed["scope"]["unit"] is None
                or f.unit == attributed["scope"]["unit"]
            )
            and isinstance(f.value, (int, float))
        ]
        if vals:
            per_qname[e["qname"]] = vals
    qnames = list(per_qname)
    for i, a in enumerate(qnames):
        for b in qnames[i + 1 :]:
            if not intervals_consistent(per_qname[a] + per_qname[b]):
                return True
    return False


def faithful_keys(records: list[dict], facts) -> set:
    """The duration and instant group keys forming the faithful tiers."""
    keys = set()
    groups: dict[tuple, list[dict]] = {}
    for rec in records:
        groups.setdefault(group_key(rec), []).append(rec)
    dur = {k: span_days(k[1], k[2]) for k in groups if k[0] == "duration"}
    if dur:
        keys.add(max(dur, key=lambda k: dur[k]))
    inst = [k for k in groups if k[0] == "instant"]
    if inst:
        counts: Counter = Counter()
        for f in facts:
            if not f.dimensions and f.period_type == "instant" and f.instant_date:
                counts[f.instant_date] += 1
        keys.add(max(inst, key=lambda k: (counts.get(k[1], 0), k[1])))
    return keys


def run_evaluation(
    facade: Xbrl,
    tokenizer: ConceptTokenizer,
    firm: str,
    population: str,
    term: str,
    mode: QueryMode,
    fiscal_year: int,
    textblocks: set[str],
    atom_cache: dict[str, tuple[str, frozenset]],
) -> dict:
    """Run one term/mode evaluation: facade answer, scope sweep, register measures."""
    facts = facade._filing.facts
    accession = facade._scope_accession()
    scopes = facade._fiscal.candidate_scopes(accession, fiscal_year)
    records = [
        result_record(facade.query(term, mode=mode, scope=scope), scope)
        for scope in scopes
    ]
    facade_rec = result_record(
        facade.query(term, mode=mode, fiscal_year=fiscal_year), None
    )
    faithful = replay_faithful(records, facts)
    cls = classify(facade_rec, faithful)
    attributed = attribute(facade_rec, records)
    tier_keys = faithful_keys(records, facts)

    ev: dict = {
        "population": population,
        "firm": firm,
        "term": term,
        "mode": str(mode),
        "fiscal_year": fiscal_year,
        "facade": facade_rec,
        "faithful": (
            {k: faithful[k] for k in ("status", "value", "candidates", "tier")}
            if faithful
            else None
        ),
        "classification": cls,
        "replay_mismatch": not (
            faithful
            and facade_rec["status"] == faithful["status"]
            and values_equal(facade_rec["value"], faithful["value"])
        ),
        "attributed_scope": attributed["scope"] if attributed else None,
        "n_scopes": len(records),
        "scope_conflicts": sum(1 for r in records if r["status"] == "CONFLICT"),
        "conflict_scopes": [
            {
                "scope": r["scope"],
                "value": r["value"],
                "candidates": r["candidates"],
                "in_faithful_tier": group_key(r) in tier_keys,
            }
            for r in records
            if r["status"] == "CONFLICT"
        ],
    }

    if facade_rec["status"] == "CONFLICT":
        ev["conflict_precision_duplicate"] = conflict_is_precision_duplicate(facade_rec)
    if facade_rec["status"] == "DERIVED":
        in_tier = attributed is not None and group_key(attributed) in tier_keys
        ev["derived_in_faithful_tier"] = in_tier
        if in_tier and attributed is not None:
            scope_facts = [f for f in facts if scope_matches(f, attributed["scope"])]
            ev["derived_has_reported_fact"] = any(
                f.concept_qname in attributed["candidates"]
                and isinstance(f.value, (int, float))
                for f in scope_facts
            )
    ev["textblock_candidates"] = [
        q for q in facade_rec["candidates"] if q in textblocks
    ]
    if (
        facade_rec["value"] is not None
        and facade_rec["status"] in {"REPORTED", "DERIVED"}
        and facade_rec["tier"] == "near"
        and facade_rec["equivalents"]
    ):
        ev["near_promotion"] = True
        ev["near_guard_violation"] = near_guard_violation(facade_rec, attributed, facts)
    if ev["scope_conflicts"] and facade_rec["status"] != "CONFLICT":
        tier_conflict = any(
            r["status"] == "CONFLICT" and group_key(r) in tier_keys for r in records
        )
        ev["shadowed_conflict_in_tiers"] = tier_conflict
    if term == "revenue":
        t1_unitless = next(
            (
                r
                for r in records
                if group_key(r) in tier_keys
                and r["scope"]["kind"] == "duration"
                and r["scope"]["unit"] is None
            ),
            None,
        )
        if t1_unitless is not None:
            bare = []
            for q in t1_unitless["candidates"]:
                if q not in atom_cache:
                    atom = tokenizer.tokenize(q).atom
                    atom_cache[q] = (atom.head, atom.modifiers)
                head, mods = atom_cache[q]
                if head == "H_REVENUE" and not mods:
                    bare.append(q)
            ev["bare_revenue_pool"] = bare
            ev["bare_revenue_components"] = [
                q for q in bare if q != "us-gaap:Revenues" and q not in textblocks
            ]
    if firm == "bac" and "Derivative" in term:
        ev["xva_in_pool"] = (
            any(XVA_Q in r["candidates"] for r in records if r["status"] == "AMBIGUOUS")
            or XVA_Q in facade_rec["candidates"]
        )
    return ev


def _run_battery(
    facade,
    tokenizer,
    population,
    firm,
    battery,
    fiscal_year,
    textblocks,
    atom_cache,
    evaluations,
    out_path,
) -> None:
    """Run one firm's battery, append its evaluations, and persist recordings."""
    for term, mode in battery:
        evaluations.append(
            run_evaluation(
                facade,
                tokenizer,
                firm,
                population,
                term,
                mode,
                fiscal_year,
                textblocks,
                atom_cache,
            )
        )
    atomic_write_json(out_path, evaluations, canonical=False, indent=1)
    print(f"  {firm}: done ({len(evaluations)} evaluations so far)")


def run_population(
    population: str,
    firms: list[str],
    taxonomy,
    tokenizer: ConceptTokenizer,
    out_dir: Path,
) -> list[dict]:
    """Run one census population firm by firm, writing recordings incrementally."""
    evaluations: list[dict] = []
    path = out_dir / f"recordings_{population}.json"
    for firm in firms:
        facade = make_facade(firm, taxonomy)
        facts = facade._filing.facts
        textblocks = textblock_qnames(facts)
        atom_cache: dict = {}
        supplement: list[str] = []
        if population == "probe":
            fiscal_year = 2024
            battery = [
                (term, mode)
                for terms in PROBE_TERMS.values()
                for term in terms
                for mode in (QueryMode.REPORTED_ONLY, QueryMode.VERIFY_DERIVATION)
            ]
        else:
            fiscal_year = firm_fiscal_year(facts)
            assert fiscal_year == SPAN_FY[firm], (firm, fiscal_year)
            headline = headline_revenue_qname(facts, tokenizer, fiscal_year, atom_cache)
            pinned = PINNED_CLASS_V.get(firm, [])
            supplement = [
                q for q in discovered_concepts(facts, fiscal_year) if q not in pinned
            ]
            print(
                f"  {firm}: FY{fiscal_year} headline={headline} "
                f"pinned={pinned} supplement={supplement}"
            )
            battery = [(t, QueryMode.REPORTED_ONLY) for t in SPAN_RO]
            if headline:
                battery.append((headline, QueryMode.REPORTED_ONLY))
            battery += [(t, QueryMode.REPORTED_ONLY) for t in pinned]
            battery += [(t, QueryMode.VERIFY_DERIVATION) for t in SPAN_VERIFY]
        _run_battery(
            facade,
            tokenizer,
            population,
            firm,
            battery,
            fiscal_year,
            textblocks,
            atom_cache,
            evaluations,
            path,
        )
        if population == "span" and supplement:
            extra: list[dict] = []
            _run_battery(
                facade,
                tokenizer,
                "span-supplement",
                firm,
                [(t, QueryMode.REPORTED_ONLY) for t in supplement],
                fiscal_year,
                textblocks,
                atom_cache,
                extra,
                path,
            )
            evaluations.extend(extra)
            atomic_write_json(path, evaluations, canonical=False, indent=1)
    return evaluations


def run_followup_population(
    firms: list[str],
    taxonomy,
    tokenizer: ConceptTokenizer,
    out_dir: Path,
) -> list[dict]:
    """Run the followup battery over the seed folders named by firm slug."""
    evaluations: list[dict] = []
    path = out_dir / "recordings_followup.json"
    folders = [f for f in corpus_folders() if f.split("_")[0] in firms]
    for folder in folders:
        slug = folder.split("_")[0]
        facade = make_facade_folder(folder, taxonomy)
        facts = facade._filing.facts
        fiscal_year = firm_fiscal_year(facts)
        textblocks = textblock_qnames(facts)
        atom_cache: dict = {}
        terms = list(PROBE_TERMS_FLAT) + list(EXTRA_TERMS)
        headline = headline_revenue_qname(facts, tokenizer, fiscal_year, atom_cache)
        if headline and headline not in terms:
            terms.append(headline)
        for pinned in PINNED_CLASS_V.get(slug, []):
            if pinned not in terms:
                terms.append(pinned)
        print(f"  {slug}: FY{fiscal_year} headline={headline} terms={len(terms)}")
        battery = [
            (term, mode)
            for term in terms
            for mode in (QueryMode.REPORTED_ONLY, QueryMode.VERIFY_DERIVATION)
        ]
        _run_battery(
            facade,
            tokenizer,
            "followup",
            slug,
            battery,
            fiscal_year,
            textblocks,
            atom_cache,
            evaluations,
            path,
        )
    return evaluations


def run_census(
    populations: list[str],
    firms: list[str],
    out_dir: Path,
) -> dict:
    """Run the named census populations and return the scored summary."""
    out_dir.mkdir(parents=True, exist_ok=True)
    taxonomy = load_domain_taxonomy()
    tokenizer = ConceptTokenizer(taxonomy)
    evaluations: list[dict] = []
    for population in populations:
        if population == "followup":
            wanted = firms or [f.split("_")[0] for f in corpus_folders()]
            evaluations += run_followup_population(wanted, taxonomy, tokenizer, out_dir)
            continue
        pop_firms = PROBE_FIRMS if population == "probe" else SPAN_FIRMS
        if firms:
            wanted = set(firms)
            pop_firms = [f for f in pop_firms if f in wanted]
        print(f"population {population}: {pop_firms}")
        evaluations += run_population(
            population, pop_firms, taxonomy, tokenizer, out_dir
        )
    return summarize_census(evaluations)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: run census populations and write the summary JSON."""
    parser = argparse.ArgumentParser(description="Run the scored XBRL census.")
    parser.add_argument("--out", default="/tmp/xbrl_census_out")
    parser.add_argument("--populations", default="probe,span")
    parser.add_argument("--firms", default="")
    args = parser.parse_args(argv)
    out_dir = Path(args.out)
    firms = args.firms.split(",") if args.firms else []
    populations = args.populations.split(",")
    summary = run_census(populations, firms, out_dir)
    atomic_write_json(out_dir / "summary.json", summary, canonical=False, indent=1)
    print(json.dumps(summary, indent=1))
    if firms:
        return 0
    expected = {
        name: CENSUS_EXPECTATIONS[name]
        for name in summary["populations"]
        if name in CENSUS_EXPECTATIONS
    }
    score = score_census(summary, expected)
    if not score.passed:
        for failure in score.failures:
            sys.stderr.write(f"census gate: {failure}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())


def run_pair_gate() -> object:
    """Evaluate the seeded pair set and longitudinal relations, grounded."""
    from edgar_sec.engine.xbrl.review.benchmark import (
        PAIR_SET,
        PairReport,
        evaluate_pairs,
    )
    from edgar_sec.engine.xbrl.review.relations import (
        RELATION_SET,
        evaluate_relations,
    )
    from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
    from edgar_sec.engine.xbrl.solve.cohort_lookup import CohortLookup
    from edgar_sec.engine.xbrl.solve.concept_table import build_cohort_table
    from edgar_sec.engine.xbrl.solve.query import FinancialQueryEngine
    from edgar_sec.engine.xbrl.solve.solver import XbrlConstraintSolver
    from edgar_sec.tools.xbrl_census_corpus import (
        latest_undimensioned_fact,
        load_seed_arcs,
        load_seed_facts,
        corpus_cohort_entries,
    )

    taxonomy = load_domain_taxonomy()
    entries = corpus_cohort_entries()
    lookup = CohortLookup(build_cohort_table(taxonomy, entries), entries)
    try:
        source_facts = {
            (spec.source_firm, spec.target): latest_undimensioned_fact(
                f"{spec.source_firm.lower()}_2024_10k", spec.target
            )
            for spec in PAIR_SET
            if spec.incompatibility
        }
        pairs = evaluate_pairs(lookup, PAIR_SET, source_facts)
    finally:
        lookup.close()
    engine = FinancialQueryEngine(
        XbrlConstraintSolver(EvidenceKnowledgeBase(taxonomy=taxonomy))
    )
    folder_by_accession = {
        str(entry.accession): entry.facts_path.parent.name for entry in entries
    }
    endpoints = {}
    for spec in RELATION_SET:
        for accession in (spec.pre_accession, spec.post_accession):
            folder = folder_by_accession[accession]
            endpoints[accession] = (load_seed_facts(folder), load_seed_arcs(folder))
    relations = evaluate_relations(engine, endpoints)
    return PairReport(
        total=pairs.total + relations.total,
        passed=pairs.passed + relations.passed,
        failures=pairs.failures + relations.failures,
    )


def run_battery_gate() -> object:
    """Evaluate the answerability battery against the seed bundles."""
    from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
    from edgar_sec.engine.xbrl.review.battery import BATTERY_SET, evaluate_battery
    from edgar_sec.engine.xbrl.solve.query import FinancialQueryEngine
    from edgar_sec.engine.xbrl.solve.solver import XbrlConstraintSolver
    from edgar_sec.tools.xbrl_census_corpus import (
        load_seed_arcs,
        load_seed_facts,
        corpus_cohort_entries,
    )

    taxonomy = load_domain_taxonomy()
    entries = corpus_cohort_entries()
    folder_by_accession = {
        str(entry.accession): entry.facts_path.parent.name for entry in entries
    }
    endpoints = {}
    for entry in BATTERY_SET:
        if entry.accession not in endpoints:
            folder = folder_by_accession[entry.accession]
            endpoints[entry.accession] = (
                load_seed_facts(folder),
                load_seed_arcs(folder),
            )
    engine = FinancialQueryEngine(
        XbrlConstraintSolver(EvidenceKnowledgeBase(taxonomy=taxonomy))
    )
    return evaluate_battery(engine, endpoints)
