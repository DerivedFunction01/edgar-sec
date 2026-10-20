"""CLI tool for empirical phrase collocation mining and calculation CSP solving."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import sys

from edgar_sec.engine.xbrl.discovery.cohort import (
    SeedFiling,
    load_seed_cohort,
)
from edgar_sec.engine.xbrl.normalize.duality import split_concept_tokens
from edgar_sec.engine.xbrl.parsing.linkbase_parser import parse_calculation_linkbase
from edgar_sec.engine.xbrl.evidence.mining import (
    ArcPolarityResolver,
    CollocationMiner,
    SupportCounter,
)
from edgar_sec.engine.xbrl.schema.models import CalculationArc
from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.pipelines.xbrl_review.paths import default_seed_cohort_path


def _build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser for lattice mining tool."""
    parser = argparse.ArgumentParser(
        description="Mine accounting phrases and calculation relations from cohort linkbases.",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Destination path for mined candidates JSON.",
    )
    parser.add_argument(
        "--cohort-file",
        type=Path,
        default=None,
        help="Optional path to custom seed cohort JSON.",
    )
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=None,
        help="Directory with linkbase XML fixtures for offline processing.",
    )
    parser.add_argument(
        "--min-pmi",
        type=float,
        default=0.1,
        help="Minimum PMI threshold for phrase collocation.",
    )
    parser.add_argument(
        "--min-freq",
        type=int,
        default=2,
        help="Minimum frequency for phrase candidate extraction.",
    )
    return parser


def mine_cohort_lattice(
    cohort: Sequence[SeedFiling],
    calculation_arcs_by_filing: dict[str, Sequence[CalculationArc]],
    *,
    min_pmi: float = 0.1,
    min_freq: int = 2,
) -> dict[str, list[dict[str, object]]]:
    """Mine candidate phrases and relations from cohort calculation arcs."""
    support = SupportCounter()
    all_token_seqs: list[tuple[str, ...]] = []
    all_arcs: list[CalculationArc] = []

    for filing in cohort:
        arcs = calculation_arcs_by_filing.get(filing.accession.raw, ())
        sic_str = str(filing.sic_code)
        for arc in arcs:
            all_arcs.append(arc)
            c_local = arc.child_qname.split(":")[-1]
            p_local = arc.parent_qname.split(":")[-1]

            support.observe((c_local, p_local), filing.firm, sic_str)

            c_tokens = split_concept_tokens(c_local)
            p_tokens = split_concept_tokens(p_local)
            all_token_seqs.append(c_tokens)
            all_token_seqs.append(p_tokens)

            for i in range(len(c_tokens) - 1):
                support.observe((c_tokens[i], c_tokens[i + 1]), filing.firm, sic_str)
            for i in range(len(p_tokens) - 1):
                support.observe((p_tokens[i], p_tokens[i + 1]), filing.firm, sic_str)

    miner = CollocationMiner(min_pmi=min_pmi, min_freq=min_freq)
    mined_phrases = miner.mine_bigrams(all_token_seqs, support=support)
    mined_relations = ArcPolarityResolver.resolve_arcs(all_arcs, support=support)

    return {
        "candidate_phrases": [
            {
                "phrase": list(cp.phrase),
                "frequency": cp.frequency,
                "pmi": cp.pmi,
                "firm_count": cp.firm_count,
                "sic_count": cp.sic_count,
                "scope": cp.scope,
            }
            for cp in mined_phrases
        ],
        "candidate_relations": [
            {
                "source": cr.source_concept,
                "target": cr.target_concept,
                "weight": cr.algebraic_weight,
                "relation_type": cr.relation_type,
                "formula_id": cr.formula_id,
                "firm_count": cr.firm_count,
                "sic_count": cr.sic_count,
                "scope": cr.scope,
            }
            for cr in mined_relations
        ],
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for XBRL lattice candidate mining."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    paths = resolve_xbrl_paths()
    cohort_source = args.cohort_file or default_seed_cohort_path()
    if not cohort_source.exists():
        sys.stderr.write(f"Cohort file not found: {cohort_source}\n")
        return 1

    cohort = load_seed_cohort(cohort_source)
    fixtures_dir = args.fixtures_dir or paths.default_taxonomy_dir.parent

    calc_arcs: dict[str, list[CalculationArc]] = {}
    for filing in cohort:
        calc_files = list(fixtures_dir.glob(f"*{filing.firm.lower()}*_cal.xml"))
        if not calc_files:
            calc_files = list(fixtures_dir.glob("*_cal.xml"))
        for cf in calc_files:
            arcs = parse_calculation_linkbase(cf.read_bytes())
            calc_arcs.setdefault(filing.accession.raw, []).extend(arcs)

    result = mine_cohort_lattice(
        cohort,
        calc_arcs,
        min_pmi=args.min_pmi,
        min_freq=args.min_freq,
    )

    out_path = args.output or (paths.artifacts_root / "xbrl" / "mined_candidates.json")
    atomic_write_json(out_path, result, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
