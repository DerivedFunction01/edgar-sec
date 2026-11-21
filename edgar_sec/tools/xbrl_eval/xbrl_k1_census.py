"""K1 census: dimensioned-only quarantine mass per form x taxonomy.

A K1 fact is a numeric dimensioned fact whose concept carries no
undimensioned numeric fact in its filing; dispositions partition the
mass by the evidence that accounts for it.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

from edgar_sec.engine.xbrl.review.cross_form import K1_EXPECTATIONS, score_k1
from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.taxonomy.archive import current_table
from edgar_sec.engine.xbrl.taxonomy.item_types import declaration_for, item_type_local
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.pipelines.xbrl_review.bundles import (
    _canonical_registry_paths,
    load_filing,
    registry_filings,
)
from edgar_sec.tools.xbrl_eval.xbrl_cross_form_census import _taxonomy

SCHEDULE_TAXONOMIES = frozenset({"oef", "cef", "rxp", "us-gaap-ebp", "invest"})
DISPOSITIONS = ("per_share", "schedule", "breakdown_served", "calc_component", "orphan")


def disposition_for(
    concept: str,
    taxonomy: str,
    in_arcs: bool,
    served_global: bool,
    per_share: bool,
) -> str:
    """One K1 concept's disposition, in evidence-priority order."""
    if per_share:
        return "per_share"
    if taxonomy in SCHEDULE_TAXONOMIES:
        return "schedule"
    if served_global:
        return "breakdown_served"
    if in_arcs:
        return "calc_component"
    return "orphan"


def filing_k1_blocks(
    facts: tuple[XbrlFact, ...],
    calc_arcs: tuple[CalculationArc, ...],
    served_global: set[str],
    is_per_share: Callable[[str], bool],
) -> dict[str, Counter]:
    """K1 counts per taxonomy for one filing, split by role and disposition."""
    in_arc_qnames: set[str] = set()
    for arc in calc_arcs:
        in_arc_qnames.add(arc.parent_qname)
        in_arc_qnames.add(arc.child_qname)
    undimensioned_numeric = {
        fact.concept_qname
        for fact in facts
        if isinstance(fact.value, (int, float)) and not fact.dimensions
    }
    grouped: dict[str, list[XbrlFact]] = defaultdict(list)
    for fact in facts:
        if (
            isinstance(fact.value, (int, float))
            and fact.dimensions
            and fact.concept_qname not in undimensioned_numeric
        ):
            grouped[fact.concept_qname].append(fact)
    blocks: dict[str, Counter] = defaultdict(Counter)
    for concept, members in grouped.items():
        taxonomy = _taxonomy(concept)
        block = blocks[taxonomy]
        disposition = disposition_for(
            concept,
            taxonomy,
            concept in in_arc_qnames,
            concept in served_global,
            is_per_share(concept),
        )
        block["k1_facts"] += len(members)
        block[disposition] += len(members)
        block["in_calc_arcs" if concept in in_arc_qnames else "no_calc_role"] += len(
            members
        )
    return blocks


def _anchor_probe(
    facts: tuple[XbrlFact, ...],
    grouped: dict[str, list[XbrlFact]],
    dispositions: dict[str, str],
) -> Counter:
    """Single-axis partition sums that land on an undimensioned filed value."""
    undimensioned_values: dict[tuple, list[float]] = defaultdict(list)
    for fact in facts:
        if isinstance(fact.value, (int, float)) and not fact.dimensions:
            key = (fact.start_date, fact.end_date, fact.instant_date, fact.unit)
            undimensioned_values[key].append(float(fact.value))
    counts: Counter = Counter()
    for concept, members in grouped.items():
        groups: dict[tuple, list[XbrlFact]] = defaultdict(list)
        for fact in members:
            dims = tuple(sorted(fact.dimensions.items()))
            for drop in range(len(dims)):
                key = (
                    fact.start_date,
                    fact.end_date,
                    fact.instant_date,
                    fact.unit,
                    dims[drop][0],
                    dims[:drop] + dims[drop + 1 :],
                )
                groups[key].append(fact)
        for key, group in groups.items():
            if len(group) < 2 or len({f.dimensions[key[4]] for f in group}) != len(
                group
            ):
                continue
            disposition = dispositions[concept]
            counts[f"groups:{disposition}"] += 1
            total = sum(float(f.value) for f in group)
            tolerance = max(1.0, abs(total) * 1e-6)
            candidates = undimensioned_values.get(key[:4], [])
            if any(abs(total - value) <= tolerance for value in candidates):
                counts[f"verified:{disposition}"] += 1
    return counts


def run_k1(out_dir: Path) -> dict:
    """Run the K1 census over every standing corpus and write its summary."""
    out_dir.mkdir(parents=True, exist_ok=True)
    loaded = []
    for registry_path in _canonical_registry_paths():
        for seed in registry_filings(registry_path=registry_path):
            loaded.append((seed, load_filing(seed, registry_path)))
    served_global = {
        fact.concept_qname
        for _seed, filing in loaded
        for fact in filing.facts
        if isinstance(fact.value, (int, float)) and not fact.dimensions
    }
    table = current_table()
    blocks: dict[str, dict] = {}
    families: dict[str, Counter] = defaultdict(Counter)
    anchors: Counter = Counter()
    for seed, filing in loaded:
        per_share_cache: dict[str, bool] = {}

        def is_per_share(concept: str) -> bool:
            if concept not in per_share_cache:
                declaration = declaration_for(concept, table, filing.declarations)
                per_share_cache[concept] = bool(
                    declaration is not None
                    and item_type_local(declaration.item_type) == "perShareItemType"
                )
            return per_share_cache[concept]

        filing_blocks = filing_k1_blocks(
            filing.facts, filing.calc_arcs, served_global, is_per_share
        )
        undimensioned_numeric = {
            fact.concept_qname
            for fact in filing.facts
            if isinstance(fact.value, (int, float)) and not fact.dimensions
        }
        grouped: dict[str, list[XbrlFact]] = defaultdict(list)
        for fact in filing.facts:
            if (
                isinstance(fact.value, (int, float))
                and fact.dimensions
                and fact.concept_qname not in undimensioned_numeric
            ):
                grouped[fact.concept_qname].append(fact)
                families[_taxonomy(fact.concept_qname)][fact.concept_qname] += 1
        in_arc_qnames = {
            qname
            for arc in filing.calc_arcs
            for qname in (arc.parent_qname, arc.child_qname)
        }
        dispositions = {
            concept: disposition_for(
                concept,
                _taxonomy(concept),
                concept in in_arc_qnames,
                concept in served_global,
                is_per_share(concept),
            )
            for concept in grouped
        }
        anchors.update(_anchor_probe(filing.facts, grouped, dispositions))
        for taxonomy, counts in filing_blocks.items():
            key = f"{seed.form}|{taxonomy}"
            entry = blocks.setdefault(
                key,
                {
                    "form": seed.form,
                    "taxonomy": taxonomy,
                    "filings": 0,
                    "k1_facts": 0,
                    "no_calc_role": 0,
                    "in_calc_arcs": 0,
                    **{name: 0 for name in DISPOSITIONS},
                },
            )
            entry["filings"] += 1
            for name, value in counts.items():
                entry[name] += value
    summary: dict[str, Any] = {
        "filings": len(loaded),
        "k1_blocks": blocks,
        "anchors": dict(anchors),
        "families": {
            taxonomy: counter.most_common(5)
            for taxonomy, counter in sorted(families.items())
        },
    }
    atomic_write_json(out_dir / "summary_k1.json", summary, canonical=False, indent=1)
    return summary


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: run the K1 census and score its pinned blocks."""
    parser = argparse.ArgumentParser(description="Run the XBRL K1 census.")
    parser.add_argument("--out", default="/tmp/xbrl_k1_out")
    args = parser.parse_args(argv)
    summary = run_k1(Path(args.out))
    total = sum(block["k1_facts"] for block in summary["k1_blocks"].values())
    print(f"filings={summary['filings']} k1_facts={total}")
    for key, block in sorted(summary["k1_blocks"].items()):
        if block["k1_facts"]:
            print(
                f"[{key}] filings={block['filings']} k1={block['k1_facts']} "
                f"no_calc={block['no_calc_role']} in_arcs={block['in_calc_arcs']}"
            )
    score = score_k1(summary)
    if not score.passed:
        for failure in score.failures:
            sys.stderr.write(f"k1 gate: {failure}\n")
        return 1
    print(f"k1 gate: PASS ({len(K1_EXPECTATIONS)} blocks pinned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
