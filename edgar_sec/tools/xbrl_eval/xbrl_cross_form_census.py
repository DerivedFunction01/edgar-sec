"""Cross-form census over the probe cohort: per form x taxonomy x shape."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.forms.common.aliases import is_transition_form
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.normalize.filed_metadata import (
    filed_metadata,
    focus_length_class,
)
from edgar_sec.engine.xbrl.review.benchmark import _ADVERSE_CLASSES
from edgar_sec.engine.xbrl.review.cross_form import (
    CROSS_FORM_EXPECTATIONS,
    block_key,
    score_cross_form,
    summarize_cross_form,
)
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.query import (
    FinancialQuery,
    FinancialQueryEngine,
    QueryMode,
)
from edgar_sec.engine.xbrl.solve.scoping import (
    AmendmentLineage,
    FactScope,
    FilingRef,
    build_lineages,
    fact_key,
    supersede_facts,
)
from edgar_sec.engine.xbrl.solve.solver import XbrlConstraintSolver
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.engine.xbrl.solve.tokenizer import ConceptTokenizer
from edgar_sec.foundation.runtime.paths import resolve_paths
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.duckdb import connect, sql_path_list
from edgar_sec.pipelines.xbrl_review.bundles import (
    LoadedFiling,
    bundle_dir_for,
    load_filing,
    registry_filings,
)
from edgar_sec.engine.xbrl.discovery.cohort import canonical_probe_cohort_path
from edgar_sec.tools.xbrl_eval.xbrl_census import run_evaluation, values_equal
from edgar_sec.tools.xbrl_eval.xbrl_census_corpus import (
    ASSETS_Q,
    CASH_Q,
    firm_fiscal_year,
    span_days,
    textblock_qnames,
)

STANDARD_TAXONOMIES = (
    "us-gaap",
    "us-gaap-ebp",
    "ifrs-full",
    "dei",
    "srt",
    "ecd",
    "cyd",
    "ffd",
    "invest",
    "rxp",
    "oef",
    "cef",
)
STATEMENT_TAXONOMIES = ("us-gaap", "ifrs-full", "us-gaap-ebp")
TERMS = ["revenue", "Net Income", "cfo", CASH_Q, ASSETS_Q, "eps"]
STATEMENT_NUMERIC_FLOOR = 25
DEI_METADATA_CONCEPTS = (
    "DocumentPeriodEndDate",
    "DocumentFiscalYearFocus",
    "DocumentFiscalPeriodFocus",
    "DocumentType",
    "CurrentFiscalYearEndDate",
    "DocumentAnnualReport",
    "DocumentQuarterlyReport",
    "DocumentTransitionReport",
    "AmendmentFlag",
)


def _taxonomy(qname: str) -> str:
    """Standard taxonomy prefix of a qname, or 'extension'."""
    prefix = qname.split(":", 1)[0]
    return prefix if prefix in STANDARD_TAXONOMIES else "extension"


def dei_metadata_present(facts: tuple[XbrlFact, ...]) -> set[str]:
    """Filed dei period/fiscal metadata concepts present in one filing."""
    seen = {fact.concept_qname for fact in facts}
    return {name for name in DEI_METADATA_CONCEPTS if f"dei:{name}" in seen}


def _shape(facts: list[XbrlFact]) -> str:
    """Period shape of one taxonomy block from its facts' spans."""
    classes: Counter = Counter()
    for fact in facts:
        if fact.period_type == "duration":
            days = span_days(fact.start_date, fact.end_date)
            if days is None:
                continue
            classes[
                "annual" if days >= 300 else "ytd" if days >= 121 else "quarterly"
            ] += 1
    if classes:
        return classes.most_common(1)[0][0]
    if any(fact.period_type == "instant" for fact in facts):
        return "instant"
    return "none"


def analyze_facts(facts: tuple[XbrlFact, ...]) -> dict:
    """Per-taxonomy fact disposition plus the filing's primary block."""
    by_tax: dict[str, list[XbrlFact]] = {}
    for fact in facts:
        by_tax.setdefault(_taxonomy(fact.concept_qname), []).append(fact)
    undimensioned: dict[str, set[str]] = {}
    for tax, rows in by_tax.items():
        undimensioned[tax] = {f.concept_qname for f in rows if not f.dimensions}
    blocks: dict[str, dict] = {}
    for tax, rows in by_tax.items():
        if tax == "extension":
            continue
        numeric = [f for f in rows if isinstance(f.value, (int, float))]
        blocks[tax] = {
            "taxonomy": tax,
            "period_shape": _shape(rows),
            "facts": len(rows),
            "numeric_facts": len(numeric),
            "dimensioned_numeric": sum(1 for f in numeric if f.dimensions),
            "quarantined_facts": sum(
                1
                for f in numeric
                if f.dimensions and f.concept_qname not in undimensioned[tax]
            ),
        }
    statement = {
        tax: block
        for tax, block in blocks.items()
        if tax in STATEMENT_TAXONOMIES
        and sum(
            1
            for f in by_tax[tax]
            if isinstance(f.value, (int, float)) and not f.dimensions
        )
        >= STATEMENT_NUMERIC_FLOOR
    }
    if statement:
        primary = max(statement, key=lambda tax: statement[tax]["numeric_facts"])
        return {"blocks": blocks, "primary": primary, "statement": True}
    closed = {tax: block for tax, block in blocks.items() if tax != "dei"}
    if closed:
        primary = max(closed, key=lambda tax: closed[tax]["facts"])
    else:
        primary = "dei"
    return {"blocks": blocks, "primary": primary, "statement": False}


_FOCUS_SHAPES = {
    "ANNUAL": "annual",
    "QUARTER": "quarterly",
    "YTD_2Q": "ytd",
    "YTD_3Q": "ytd",
}


def _transition_shape(facts: tuple[XbrlFact, ...], span_shape: str) -> str:
    """A transition filing's period shape, classified by its filed dei.

    Dei period focus names the class (Step 5 authority comparison); the
    span shape is the fallback where the focus names no class.
    """
    focus_class = focus_length_class(filed_metadata(facts).period_focus)
    return _FOCUS_SHAPES.get(focus_class or "", span_shape)


def _catalog_part_paths(catalog_dir: Path | None) -> list[Path]:
    """Catalog parquet parts: an explicit dir, else the local snapshot."""
    if catalog_dir is not None:
        return (
            sorted(catalog_dir.glob("*.parquet"))
            or sorted(catalog_dir.glob("parts/*.parquet"))
            or sorted(catalog_dir.glob("*/parts/*.parquet"))
        )
    snapshots = resolve_paths().artifacts_root / "metadata" / "snapshots"
    return sorted(snapshots.glob("*/parts/*.parquet"))


def _filing_refs(
    seeds: list,
    loaded_by_accession: dict[str, LoadedFiling],
    catalog_dir: Path | None,
) -> list[FilingRef]:
    """Lineage refs for registry filings, from the submissions catalog.

    A filing the snapshot does not carry falls back to its registry
    form and filed dei period end.
    """
    refs: dict[str, FilingRef] = {}
    parts = _catalog_part_paths(catalog_dir)
    if parts:
        con = connect()
        try:
            rows = con.execute(
                "SELECT cik, f.accession_number, f.form, f.filing_date, "
                "f.report_date FROM (SELECT cik, unnest(filings) AS f "
                f"FROM read_parquet({sql_path_list([str(p) for p in parts])})) "
                "WHERE f.accession_number = ANY(?)",
                [[str(seed.accession) for seed in seeds]],
            ).fetchall()
        finally:
            con.close()
        for cik, accession, form, filed, period in rows:
            if period:
                refs[str(accession)] = FilingRef(
                    accession=str(accession),
                    cik=str(cik),
                    form=str(form),
                    report_period=str(period),
                    filed_date=str(filed or ""),
                )
    for seed in seeds:
        accession = str(seed.accession)
        if accession in refs:
            continue
        period_end = filed_metadata(loaded_by_accession[accession].facts).period_end
        if period_end:
            refs[accession] = FilingRef(
                accession=accession,
                cik=str(seed.cik),
                form=seed.form,
                report_period=period_end,
            )
    return list(refs.values())


def _periods(facts: tuple[XbrlFact, ...]) -> list[tuple]:
    """Distinct undimensioned periods a filing carries, durations first."""
    durations = sorted(
        {
            (f.start_date, f.end_date)
            for f in facts
            if f.period_type == "duration"
            and not f.dimensions
            and f.start_date
            and f.end_date
        }
    )
    instants = sorted(
        {
            f.instant_date
            for f in facts
            if f.period_type == "instant" and not f.dimensions and f.instant_date
        }
    )
    return [(start, end, None) for start, end in durations] + [
        (None, None, instant) for instant in instants
    ]


def _pair_evaluation(
    original: LoadedFiling,
    amendment: LoadedFiling,
    lineage: AmendmentLineage,
    taxonomy,
) -> dict:
    """Pooled original+amendment queries must answer from the restatement.

    Legs compare a lineage scope over the pooled facts against the
    amendment alone, plus original reachability by accession scope.
    """
    pooled = original.facts + amendment.facts
    arcs = amendment.calc_arcs
    declarations = {**original.declarations, **amendment.declarations}
    engine = FinancialQueryEngine(
        XbrlConstraintSolver(EvidenceKnowledgeBase(taxonomy=taxonomy)),
        declarations=declarations,
    )
    analysis = analyze_facts(amendment.facts)
    primary = analysis["primary"]
    primary_block = analysis["blocks"][primary]
    amendment_keys = {fact_key(fact) for fact in amendment.facts}
    key_mixed = any(
        fact_key(fact) in amendment_keys and str(fact.accession) != lineage.latest
        for fact in supersede_facts(pooled, [lineage])
    )
    legs = 0
    served = 0
    conflicts = 0
    mixed_legs: list[dict] = []

    def execute(term: str, mode: QueryMode, scope: FactScope, facts):
        return engine.execute(FinancialQuery(term, scope, mode), facts, arcs)

    for start, end, instant in _periods(amendment.facts):
        for term in TERMS:
            for mode in (QueryMode.REPORTED_ONLY, QueryMode.VERIFY_DERIVATION):
                legs += 1
                pooled_result = execute(
                    term,
                    mode,
                    FactScope(
                        start_date=start,
                        end_date=end,
                        instant_date=instant,
                        lineages=(lineage,),
                    ),
                    pooled,
                )
                reference = execute(
                    term,
                    mode,
                    FactScope(
                        accession=lineage.latest,
                        start_date=start,
                        end_date=end,
                        instant_date=instant,
                    ),
                    pooled,
                )
                if str(pooled_result.status) == "CONFLICT":
                    conflicts += 1
                if reference.value is not None:
                    if not values_equal(pooled_result.value, reference.value):
                        mixed_legs.append(
                            {"term": term, "mode": str(mode), "leg": "restated"}
                        )
                    else:
                        served += 1
                elif pooled_result.value is not None:
                    served += 1
            legs += 1
            scoped_original = execute(
                term,
                QueryMode.REPORTED_ONLY,
                FactScope(
                    accession=lineage.original,
                    start_date=start,
                    end_date=end,
                    instant_date=instant,
                ),
                pooled,
            )
            alone_original = execute(
                term,
                QueryMode.REPORTED_ONLY,
                FactScope(
                    accession=lineage.original,
                    start_date=start,
                    end_date=end,
                    instant_date=instant,
                ),
                original.facts,
            )
            if not values_equal(scoped_original.value, alone_original.value) or (
                scoped_original.value is None
            ) != (alone_original.value is None):
                mixed_legs.append({"term": term, "leg": "original-reachability"})
    classification = (
        "mixed-population"
        if key_mixed or mixed_legs
        else "correct"
        if served
        else "honest-faithful"
    )
    return {
        "population": "cross-form",
        "firm": amendment.seed.firm,
        "form": f"{original.seed.form}+{amendment.seed.form}",
        "taxonomy": primary,
        "period_shape": primary_block["period_shape"],
        "classification": classification,
        "facade": {
            "status": "CONFLICT" if conflicts else "UNAVAILABLE",
            "value": None,
        },
        "replay_mismatch": False,
        "quarantined_facts": primary_block["quarantined_facts"],
        "conflict_evaluations": conflicts,
        "accession": str(amendment.seed.accession),
        "pair": {
            "original": lineage.original,
            "amendment": lineage.latest,
            "legs": legs,
            "served_legs": served,
            "key_mixed": key_mixed,
            "mixed_legs": mixed_legs[:6],
        },
    }


def _absence_evaluation(
    facade: Xbrl, seed, primary: str, shape: str, quarantined: int
) -> dict:
    """Financial terms on a non-statement filing must serve nothing."""
    conflicts = 0
    served: list[str] = []
    for term in TERMS:
        result = facade.query(term, mode=QueryMode.REPORTED_ONLY, fiscal_year=seed.fy)
        if str(result.status) == "CONFLICT":
            conflicts += 1
        if result.value is not None:
            served.append(term)
    classification = "wrong-value" if served else "honest-faithful"
    return {
        "population": "cross-form",
        "firm": seed.firm,
        "form": seed.form,
        "taxonomy": primary,
        "period_shape": shape,
        "classification": classification,
        "facade": {
            "status": "CONFLICT" if conflicts else "UNAVAILABLE",
            "value": None,
        },
        "replay_mismatch": False,
        "quarantined_facts": quarantined,
        "conflict_evaluations": conflicts,
        "served_terms": served,
        "accession": str(seed.accession),
    }


def _statement_evaluation(
    facade: Xbrl, tokenizer, seed, primary: str, shape: str, quarantined: int
) -> dict:
    """Term battery over a statement filing, replayed like the census."""
    facts = facade._filing.facts
    try:
        fiscal_year = firm_fiscal_year(facts)
    except Exception:  # noqa: BLE001 - cohort fy is the fallback shape
        fiscal_year = seed.fy
    textblocks = textblock_qnames(facts)
    atom_cache: dict = {}
    evaluations = [
        run_evaluation(
            facade,
            tokenizer,
            seed.firm.lower(),
            "cross-form",
            term,
            mode,
            fiscal_year,
            textblocks,
            atom_cache,
        )
        for term in TERMS
        for mode in (QueryMode.REPORTED_ONLY, QueryMode.VERIFY_DERIVATION)
    ]
    adverse = next(
        (ev for ev in evaluations if ev["classification"] in _ADVERSE_CLASSES),
        None,
    )
    conflicts = sum(1 for ev in evaluations if ev["facade"]["status"] == "CONFLICT")
    if adverse is not None:
        classification = adverse["classification"]
    elif any(ev["classification"] == "correct" for ev in evaluations):
        classification = "correct"
    else:
        classification = "honest-faithful"
    return {
        "population": "cross-form",
        "firm": seed.firm,
        "form": seed.form,
        "taxonomy": primary,
        "period_shape": shape,
        "classification": classification,
        "facade": {
            "status": "CONFLICT" if conflicts else evaluations[0]["facade"]["status"],
            "value": None,
        },
        "replay_mismatch": any(ev["replay_mismatch"] for ev in evaluations),
        "quarantined_facts": quarantined,
        "conflict_evaluations": conflicts,
        "solved_evaluations": sum(
            1 for ev in evaluations if ev["classification"] == "correct"
        ),
        "honest_evaluations": sum(
            1 for ev in evaluations if ev["classification"] == "honest-faithful"
        ),
        "term_evaluations": [
            {
                "term": ev["term"],
                "mode": ev["mode"],
                "classification": ev["classification"],
                "status": ev["facade"]["status"],
                "value": ev["facade"]["value"],
            }
            for ev in evaluations
        ],
        "accession": str(seed.accession),
    }


def run_cross_form(out_dir: Path, catalog_dir: Path | None = None) -> dict:
    """Run the cross-form census over the whole probe cohort registry."""
    out_dir.mkdir(parents=True, exist_ok=True)
    registry_path = canonical_probe_cohort_path()
    taxonomy = load_domain_taxonomy()
    tokenizer = ConceptTokenizer(taxonomy)
    evaluations: list[dict] = []
    fact_rows: list[dict] = []
    presence: dict[str, dict] = {}
    seeds = list(registry_filings(registry_path=registry_path))
    loaded_by_accession: dict[str, LoadedFiling] = {}
    for seed in seeds:
        loaded = load_filing(seed, registry_path)
        loaded_by_accession[str(seed.accession)] = loaded
        family = presence.setdefault(
            seed.form,
            {
                "filings": 0,
                "present": {name: 0 for name in DEI_METADATA_CONCEPTS},
            },
        )
        family["filings"] += 1
        for name in dei_metadata_present(loaded.facts):
            family["present"][name] += 1
        analysis = analyze_facts(loaded.facts)
        for block in analysis["blocks"].values():
            fact_rows.append({"form": seed.form, "firm": seed.firm, **block})
        primary_block = analysis["blocks"].get(analysis["primary"])
        if primary_block is None:
            continue
        facade = Xbrl.from_bundle(
            bundle_dir_for(str(seed.accession), registry_path), taxonomy
        )
        shape = primary_block["period_shape"]
        if is_transition_form(seed.form):
            shape = _transition_shape(loaded.facts, shape)
        if analysis["statement"]:
            evaluation = _statement_evaluation(
                facade,
                tokenizer,
                seed,
                analysis["primary"],
                shape,
                primary_block["quarantined_facts"],
            )
        else:
            evaluation = _absence_evaluation(
                facade,
                seed,
                analysis["primary"],
                shape,
                primary_block["quarantined_facts"],
            )
        evaluations.append(evaluation)
        atomic_write_json(
            out_dir / "recordings_cross_form.json",
            evaluations,
            canonical=False,
            indent=1,
        )
        print(
            f"  {seed.firm} {seed.form}: primary={analysis['primary']} "
            f"shape={shape} -> {evaluation['classification']}"
        )
    refs = _filing_refs(seeds, loaded_by_accession, catalog_dir)
    for lineage in build_lineages(refs):
        if len(lineage.accessions) < 2 or not all(
            accession in loaded_by_accession for accession in lineage.accessions
        ):
            continue
        evaluation = _pair_evaluation(
            loaded_by_accession[lineage.original],
            loaded_by_accession[lineage.latest],
            lineage,
            taxonomy,
        )
        evaluations.append(evaluation)
        print(
            f"  pair {evaluation['form']}: -> {evaluation['classification']} "
            f"(legs={evaluation['pair']['legs']}, "
            f"mixed={len(evaluation['pair']['mixed_legs'])})"
        )
    atomic_write_json(
        out_dir / "recordings_cross_form.json",
        evaluations,
        canonical=False,
        indent=1,
    )
    summary = summarize_cross_form(evaluations)
    matrix: dict[str, dict] = {}
    for row in fact_rows:
        key = block_key(row["form"], row["taxonomy"], row["period_shape"])
        entry = matrix.setdefault(
            key,
            {
                "form": row["form"],
                "taxonomy": row["taxonomy"],
                "period_shape": row["period_shape"],
                "filings": 0,
                "facts": 0,
                "numeric_facts": 0,
                "dimensioned_numeric": 0,
                "quarantined_facts": 0,
            },
        )
        entry["filings"] += 1
        for field in (
            "facts",
            "numeric_facts",
            "dimensioned_numeric",
            "quarantined_facts",
        ):
            entry[field] += row[field]
    summary["fact_matrix"] = matrix
    summary["dei_presence"] = presence
    summary["evaluations"] = evaluations
    atomic_write_json(
        out_dir / "summary_cross_form.json", summary, canonical=False, indent=1
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: run the cross-form census and score its blocks."""
    parser = argparse.ArgumentParser(description="Run the cross-form XBRL census.")
    parser.add_argument("--out", default="/tmp/xbrl_cross_form_out")
    parser.add_argument("--catalog-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    summary = run_cross_form(Path(args.out), catalog_dir=args.catalog_dir)
    for key, block in sorted(summary["blocks"].items()):
        print(
            f"[{key}] n={block['n']} solved={block['solved']} "
            f"honest={block['honest']} conflict={block['conflict']} "
            f"quarantined={block['quarantined_facts']} adverse={block['adverse']}"
        )
    expected = {
        key: exp
        for key, exp in CROSS_FORM_EXPECTATIONS.items()
        if key in summary["blocks"]
    }
    score = score_cross_form(summary, expected)
    if not score.passed:
        for failure in score.failures:
            sys.stderr.write(f"cross-form gate: {failure}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
