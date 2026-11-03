"""Cross-form census over the probe cohort: per form x taxonomy x shape."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.engine.xbrl.review.benchmark import _ADVERSE_CLASSES
from edgar_sec.engine.xbrl.review.cross_form import (
    CROSS_FORM_EXPECTATIONS,
    block_key,
    score_cross_form,
    summarize_cross_form,
)
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.query import QueryMode
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.engine.xbrl.solve.tokenizer import ConceptTokenizer
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.pipelines.xbrl_review.bundles import (
    bundle_dir_for,
    load_filing,
    registry_filings,
)
from edgar_sec.engine.xbrl.discovery.cohort import canonical_probe_cohort_path
from edgar_sec.tools.xbrl_eval.xbrl_census import run_evaluation
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


def _taxonomy(qname: str) -> str:
    """Standard taxonomy prefix of a qname, or 'extension'."""
    prefix = qname.split(":", 1)[0]
    return prefix if prefix in STANDARD_TAXONOMIES else "extension"


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


def run_cross_form(out_dir: Path) -> dict:
    """Run the cross-form census over the whole probe cohort registry."""
    out_dir.mkdir(parents=True, exist_ok=True)
    registry_path = canonical_probe_cohort_path()
    taxonomy = load_domain_taxonomy()
    tokenizer = ConceptTokenizer(taxonomy)
    evaluations: list[dict] = []
    fact_rows: list[dict] = []
    for seed in registry_filings(registry_path=registry_path):
        loaded = load_filing(seed, registry_path)
        analysis = analyze_facts(loaded.facts)
        for block in analysis["blocks"].values():
            fact_rows.append({"form": seed.form, "firm": seed.firm, **block})
        primary_block = analysis["blocks"].get(analysis["primary"])
        if primary_block is None:
            continue
        facade = Xbrl.from_bundle(
            bundle_dir_for(str(seed.accession), registry_path), taxonomy
        )
        if analysis["statement"]:
            evaluation = _statement_evaluation(
                facade,
                tokenizer,
                seed,
                analysis["primary"],
                primary_block["period_shape"],
                primary_block["quarantined_facts"],
            )
        else:
            evaluation = _absence_evaluation(
                facade,
                seed,
                analysis["primary"],
                primary_block["period_shape"],
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
            f"shape={primary_block['period_shape']} -> {evaluation['classification']}"
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
    summary["evaluations"] = evaluations
    atomic_write_json(
        out_dir / "summary_cross_form.json", summary, canonical=False, indent=1
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: run the cross-form census and score its blocks."""
    parser = argparse.ArgumentParser(description="Run the cross-form XBRL census.")
    parser.add_argument("--out", default="/tmp/xbrl_cross_form_out")
    args = parser.parse_args(argv)
    summary = run_cross_form(Path(args.out))
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
