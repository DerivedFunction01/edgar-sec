"""Canonical CLI for pipeline table probe, vocabulary census, and classifier benchmarking."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from defs.runtime.paths import resolve_paths
from defs.runtime.resources import derive_resources
from defs.taxonomy.probe.audit import (
    compute_collision_matrix,
    compute_family_relations,
    compute_geometry_stats,
)
from defs.taxonomy.probe.cache import (
    build_probe_cache_from_sqlite,
    default_fixture_db_path,
    default_probe_cache_path,
)
from defs.taxonomy.probe.census import (
    census_vocabulary,
    cluster_unclassified_tables,
    compute_distinctive_ngrams,
)
from defs.taxonomy.probe.inspector import inspect_table_record
from defs.taxonomy.probe.rules import load_external_rules, load_parquet_records
from defs.taxonomy.tables.classifier import classify_table
from defs.taxonomy.tables.families import FAMILY_SPECS
from defs.taxonomy.tables.specs import TableFamilySpec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pipeline Table Probe, Cross-Firm Vocabulary Census, and Multi-Zone Classifier CLI",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=default_probe_cache_path(),
        help="Path to healed probe parquet cache",
    )
    parser.add_argument(
        "--build-cache",
        action="store_true",
        help="Extract & heal tables into cache from fixture SQLite database",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=default_fixture_db_path(),
        help="Path to fixture SQLite database for cache build",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Target number of table-bearing filings when building cache",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Worker process count for extraction (defaults to machine-derived runtime workers)",
    )
    parser.add_argument(
        "--family",
        type=str,
        help="Target table family name for evaluation, census, or filtering",
    )
    parser.add_argument(
        "--rules",
        type=Path,
        help="Path to custom Python script declaring TableFamilySpecs",
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Discover distinctive n-grams for candidate tables matching --seed",
    )
    parser.add_argument(
        "--seed",
        nargs="+",
        help="Seed keywords for candidate table discovery",
    )
    parser.add_argument(
        "--census",
        action="store_true",
        help="Run cross-firm vocabulary census across specified zone and n-gram order",
    )
    parser.add_argument(
        "--ngram",
        type=int,
        default=2,
        choices=[1, 2, 3, 4],
        help="N-gram order (1=unigrams, 2=bigrams, 3=trigrams, 4=4-grams)",
    )
    parser.add_argument(
        "--zone",
        type=str,
        default="row_labels",
        choices=["row_labels", "headers", "full"],
        help="Table zone for vocabulary census",
    )
    parser.add_argument(
        "--audit-gate",
        action="store_true",
        help="Run collision audit and sole-match evaluation",
    )
    parser.add_argument(
        "--relations",
        action="store_true",
        help="Compute cross-family relations, subsumptions, and overlap rates",
    )
    parser.add_argument(
        "--geometry",
        action="store_true",
        help="Compute empirical post-healing 2D geometry (columns, rows, jitter)",
    )
    parser.add_argument(
        "--inspect",
        type=int,
        help="Inspect 2D grid and template rendering preview for table at index",
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Run full multi-zone BoW classifier benchmark over entire dataset",
    )
    parser.add_argument(
        "--cluster-unclassified",
        action="store_true",
        help="Group unclassified tables into candidate clusters by recurring row-stub n-grams",
    )
    parser.add_argument(
        "--synthesize-spec",
        type=str,
        help="Auto-synthesize optimal non-colliding TableFamilySpec JSON for a candidate signature",
    )
    parser.add_argument(
        "--detect-unions",
        action="store_true",
        help="Detect multi-part table schedule candidates (adjacent tables under identical heading)",
    )
    parser.add_argument(
        "--json",
        type=Path,
        help="Write structured results to JSON file",
    )

    args = parser.parse_args(argv)

    if args.build_cache:
        workers = (
            args.workers if args.workers is not None else derive_resources().workers
        )
        print(
            f"Building probe cache from {args.db_path} (target={args.limit} table-bearing filings, workers={workers})..."
        )
        out_p = build_probe_cache_from_sqlite(
            db_path=args.db_path,
            output_path=args.cache,
            limit=args.limit,
            workers=workers,
        )
        print(f"Successfully created probe cache at {out_p}")
        return 0

    if not args.cache.exists():
        # Fallback to alternative cache under test_runs_root if available
        project = resolve_paths()
        scratch_dir = project.test_runs_root / "scratch"
        fallback_candidates = [
            scratch_dir / name
            for name in (
                "table-healed-probe-500.parquet",
                "table-healed-probe-250.parquet",
                "table-healed-probe-25.parquet",
                "table-identity-probe-250.parquet",
            )
        ]
        found = False
        for cand in fallback_candidates:
            if cand.exists():
                args.cache = cand
                found = True
                break
        if not found:
            print(
                f"Cache file {args.cache} not found. Use --build-cache to build it.",
                file=sys.stderr,
            )
            return 1

    records = load_parquet_records(args.cache)
    non_toc_records = [r for r in records if not r.get("is_toc", False)]
    print(
        f"Loaded {len(records)} tables ({len(non_toc_records)} non-TOC) from {args.cache.name}"
    )

    active_specs: dict[str, TableFamilySpec] = dict(FAMILY_SPECS)
    if args.rules:
        loaded = load_external_rules(args.rules)
        active_specs.update(loaded)
        print(
            f"Loaded {len(loaded)} custom specs from {args.rules}: {sorted(loaded.keys())}"
        )

    # Mode: Inspect single table
    if args.inspect is not None:
        idx = args.inspect
        if 0 <= idx < len(non_toc_records):
            print(inspect_table_record(non_toc_records[idx]))
        else:
            print(
                f"Error: index {idx} out of range [0..{len(non_toc_records) - 1}]",
                file=sys.stderr,
            )
            return 1
        return 0

    # Mode: Corpus Vocabulary Census
    if args.census:
        print(
            f"\n--- Vocabulary Census: Zone={args.zone}, Order={args.ngram}-grams ---"
        )
        items = census_vocabulary(
            non_toc_records, n=args.ngram, zone=args.zone, top_k=30
        )
        for rank, itm in enumerate(items, start=1):
            print(
                f"{rank:2}. {itm['term']:35} docs={itm['doc_count']:4} ({float(itm['doc_frequency']):.1%}) total={itm['total_occurrences']:5}"
            )
        return 0

    # Mode: Discovery
    if args.discover:
        if not args.seed:
            print("Error: --discover requires --seed <terms...>", file=sys.stderr)
            return 1
        seed_terms = [s.lower() for s in args.seed]
        target_recs = [
            r
            for r in non_toc_records
            if all(
                s in str(r.get("full_normalized_text", "")).lower() for s in seed_terms
            )
        ]
        bg_recs = [
            r
            for r in non_toc_records
            if not all(
                s in str(r.get("full_normalized_text", "")).lower() for s in seed_terms
            )
        ]
        print(
            f"Discovery: matched {len(target_recs)} candidate tables matching seed {seed_terms}"
        )

        target_row_texts = [
            str(r.get("row_labels_text", r.get("text", ""))) for r in target_recs
        ]
        bg_row_texts = [
            str(r.get("row_labels_text", r.get("text", ""))) for r in bg_recs
        ]

        ngrams = compute_distinctive_ngrams(
            target_row_texts, bg_row_texts, n=args.ngram, top_k=20
        )

        print(f"\n--- Top Distinctive {args.ngram}-grams in Row Stubs (Col 0) ---")
        for item in ngrams:
            print(
                f"  {item['term']:35} docs={item['target_docs']:3} (spec={float(item['specificity']):.1%}) score={item['score']}"
            )

        if args.geometry:
            geom = compute_geometry_stats(target_recs)
            print("\n--- Post-Healing 2D Geometry ---")
            print(json.dumps(geom, indent=2))
        return 0

    # Mode: Benchmark Classifier & Audit Gate
    if args.benchmark or args.audit_gate or args.relations:
        print("\nRunning Multi-Zone BoW Classifier Benchmark on Corpus...")
        matches_per_family: dict[str, set[int]] = {name: set() for name in active_specs}
        classified_slots: set[int] = set()

        for slot, rec in enumerate(non_toc_records):
            grid_raw = rec.get("healed_grid_json")
            if grid_raw:
                grid = json.loads(str(grid_raw))
            else:
                grid = [[c] for c in str(rec.get("text", "")).split()[:10]]

            res = classify_table(grid)
            if res.family and res.family in matches_per_family:
                matches_per_family[res.family].add(slot)
                classified_slots.add(slot)

        print("\n=== Classification Summary ===")
        for name, slots in sorted(matches_per_family.items()):
            sole_matches = sum(
                1
                for s in slots
                if sum(
                    1 for fam, fam_slots in matches_per_family.items() if s in fam_slots
                )
                == 1
            )
            sole_rate = (sole_matches / len(slots) * 100) if slots else 0.0
            print(
                f"{name:26} carriers={len(slots):5} sole_matches={sole_matches:5} ({sole_rate:5.1f}%)"
            )

        matrix = compute_collision_matrix(matches_per_family)
        collisions: list[tuple[str, str, int]] = []
        for fam_a, col_dict in matrix.items():
            for fam_b, count in col_dict.items():
                if fam_a < fam_b and count > 0:
                    collisions.append((fam_a, fam_b, count))

        if collisions:
            print("\n=== Cross-Family Collisions ===")
            for fam_a, fam_b, count in sorted(
                collisions, key=lambda x: x[2], reverse=True
            ):
                print(f"  {fam_a} + {fam_b}: {count}")
        else:
            print(
                "\n=== Cross-Family Collisions: ZERO collisions detected (100% orthogonal) ==="
            )

        if args.relations:
            relations = compute_family_relations(matches_per_family)
            if relations:
                print("\n=== Cross-Family Overlap & Subsumption Relations ===")
                for rel in relations:
                    print(
                        f"  {rel['family_a']} -> {rel['family_b']}: overlap={rel['overlap_count']} (rate_a={rel['rate_in_a']:.1%}, rate_b={rel['rate_in_b']:.1%}) [{rel['relation_type']}]"
                    )

        total_cov = len(classified_slots) / max(1, len(non_toc_records))
        print(
            f"\nTotal Classified Tables: {len(classified_slots)} / {len(non_toc_records)} ({total_cov:.1%})"
        )

    # Mode: Cluster Unclassified Tables
    if args.cluster_unclassified:
        print("\nGrouping unclassified tables into candidate clusters...")
        unclassified_records: list[dict[str, Any]] = []
        for rec in non_toc_records:
            grid_raw = rec.get("healed_grid_json")
            grid = json.loads(str(grid_raw)) if grid_raw else []
            res = classify_table(grid) if grid else None
            if res is None or res.family is None:
                unclassified_records.append(rec)

        print(f"Analyzing {len(unclassified_records)} unclassified tables...")
        clusters = cluster_unclassified_tables(
            unclassified_records, min_cluster_size=3, top_k=25
        )

        print("\n=== Top Recurring Unclassified Table Clusters ===")
        for idx, c in enumerate(clusters, start=1):
            print(
                f"{idx:2}. Signature: '{c['signature']}' ({c['table_count']} tables | avg cols: {c['avg_cols']} | avg rows: {c['avg_rows']} | num density: {c['avg_numeric_density']})"
            )
            if c["sample_headings"]:
                print(f"    Sample Headings: {c['sample_headings']}")
            print()

    # Mode: Detect Multi-Part Unions
    if args.detect_unions:
        print("\nDetecting multi-part table schedule candidates across filings...")
        from defs.taxonomy.probe.optimizer import detect_union_candidates

        unions = detect_union_candidates(non_toc_records)
        print(f"Found {len(unions)} candidate multi-part table groups.")
        for u in unions[:20]:
            print(
                f"Doc {u['doc_id']}: '{u['heading']}' -> {u['table_count']} parts (indices: {u['table_indices']})"
            )
        return 0

    # Mode: Synthesize Spec
    if args.synthesize_spec:
        target_sig = args.synthesize_spec.lower()
        print(
            f"\nAuto-synthesizing non-colliding TableFamilySpec for signature '{target_sig}'..."
        )
        from defs.taxonomy.probe.optimizer import synthesize_candidate_family

        target_records = [
            r
            for r in non_toc_records
            if target_sig in str(r.get("row_labels_text", "")).lower()
            or target_sig in str(r.get("heading", "")).lower()
        ]
        bg_records = [
            r
            for r in non_toc_records
            if target_sig not in str(r.get("row_labels_text", "")).lower()
            and target_sig not in str(r.get("heading", "")).lower()
        ]

        if not target_records:
            print(f"Error: No tables matched signature '{target_sig}'", file=sys.stderr)
            return 1

        spec_json = synthesize_candidate_family(
            target_records,
            bg_records,
            cluster_name=target_sig.replace(" ", "_"),
        )
        print("\n=== Synthesized Spec Definition ===")
        print(json.dumps(spec_json, indent=2))
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
