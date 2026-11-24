"""Scored census regression over the grounded XBRL seed fixtures."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.engine.xbrl.review.benchmark_census import (
    score_census,
    summarize_census,
)
from edgar_sec.engine.xbrl.review.census_expectations import CENSUS_EXPECTATIONS
from edgar_sec.engine.xbrl.solve.concepts.tokenizer import ConceptTokenizer
from edgar_sec.engine.xbrl.solve.core.query import QueryMode
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.tools.xbrl_eval.xbrl_census_corpus import (
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
    textblock_qnames,
)
from edgar_sec.tools.xbrl_eval.xbrl_census_replay import (
    attribute,
    classify,
    conflict_is_precision_duplicate,
    faithful_keys,
    group_key,
    near_guard_violation,
    replay_faithful,
    result_record,
    scope_matches,
    values_equal,
)


REPO = Path(__file__).resolve().parents[3]


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
