"""Canonical CLI for pipeline table probe, vocabulary census, and classifier benchmarking."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from defs.runtime.resources import derive_resources
from defs.taxonomy.probe.audit import (
    compute_collision_matrix,
    compute_family_relations,
    compute_geometry_stats,
    run_benchmark_classifier,
)
from defs.taxonomy.probe.cache import (
    build_probe_cache_from_sqlite,
    default_fixture_db_path,
    default_probe_cache_path,
)
from defs.taxonomy.probe.census import (
    census_vocabulary,
    compute_distinctive_ngrams,
)
from defs.taxonomy.probe.exporter import export_family_dataset
from defs.taxonomy.probe.inspector import inspect_table_record
from defs.taxonomy.probe.rules import (
    count_probe_cache_tables,
    load_external_rules,
    query_probe_parquet,
)
from defs.taxonomy.tables.families import FAMILY_SPECS
from defs.taxonomy.tables.specs import TableFamilySpec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pipeline Table Probe, Cross-Firm Vocabulary Census, and Multi-Zone Classifier CLI",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=None,
        help="Path to healed probe parquet cache (defaults to auto-discovered cache in .artifacts/taxonomy/probe/)",
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
        "--profile",
        action="store_true",
        help="Run comprehensive empirical profile for --family (dimensions, jitter, top headers/rows)",
    )
    parser.add_argument(
        "--show-jittery-samples",
        type=int,
        default=0,
        help="Number of jittery / high-defect table samples to dump during profiling",
    )
    parser.add_argument(
        "--export-dataset",
        action="store_true",
        help="Export a family-specific Parquet dataset with HTML, healed grids, and rendered output",
    )
    parser.add_argument(
        "--output-parquet",
        type=Path,
        default=None,
        help="Custom output path for the exported Parquet dataset",
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

    cache_path = args.cache if args.cache is not None else default_probe_cache_path()
    if not cache_path.exists():
        print(
            f"Cache file {cache_path} not found. Use --build-cache to build it.",
            file=sys.stderr,
        )
        return 1

    total_tables, non_toc_count = count_probe_cache_tables(cache_path)
    print(
        f"Probe cache: {total_tables:,} tables ({non_toc_count:,} non-TOC) in {cache_path.name}"
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
        recs = query_probe_parquet(
            cache_path,
            where_clause="is_toc = false",
            limit=idx + 1,
        )
        if 0 <= idx < len(recs):
            print(inspect_table_record(recs[idx]))
        else:
            print(
                f"Error: index {idx} out of range [0..{non_toc_count - 1}]",
                file=sys.stderr,
            )
            return 1
        return 0

    # Mode: Corpus Vocabulary Census
    if args.census:
        print(
            f"\n--- Vocabulary Census: Zone={args.zone}, Order={args.ngram}-grams ---"
        )
        zone_key = {
            "row_labels": "row_labels_text",
            "header": "header_text",
            "full": "full_normalized_text",
        }.get(args.zone, "row_labels_text")
        census_records = query_probe_parquet(
            cache_path,
            where_clause="is_toc = false",
            columns=[zone_key],
        )
        items = census_vocabulary(
            census_records, n=args.ngram, zone=args.zone, top_k=30
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
        seed_terms = [s.lower().replace("'", "''") for s in args.seed]
        where_target = " OR ".join(
            f"lower(full_normalized_text) LIKE '%{s}%' OR lower(row_labels_text) LIKE '%{s}%' OR lower(header_text) LIKE '%{s}%' OR lower(heading) LIKE '%{s}%'"
            for s in seed_terms
        )
        target_recs = query_probe_parquet(
            cache_path,
            where_clause=f"is_toc = false AND ({where_target})",
            columns=[
                "row_labels_text",
                "heading",
                "healed_cols",
                "healed_rows",
                "numeric_density",
                "header_count",
                "has_column_jitter",
                "has_split_affixes",
            ],
        )
        bg_recs = query_probe_parquet(
            cache_path,
            where_clause=f"is_toc = false AND NOT ({where_target})",
            columns=["row_labels_text"],
            limit=50000,
        )

        print(
            f"Discovery: matched {len(target_recs)} candidate tables matching seeds {args.seed}"
        )

        target_row_texts = [
            str(r.get("row_labels_text", "") or "") for r in target_recs
        ]
        bg_row_texts = [str(r.get("row_labels_text", "") or "") for r in bg_recs]

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
        workers = (
            args.workers if args.workers is not None else derive_resources().workers
        )
        workers = max(1, workers)
        print(
            f"\nRunning Multi-Zone BoW Classifier Benchmark on Corpus ({workers} workers)..."
        )
        bench_records = query_probe_parquet(
            cache_path,
            where_clause="is_toc = false",
            columns=["healed_grid_json"],
        )

        matches_per_family, classified_slots = run_benchmark_classifier(
            bench_records=bench_records,
            active_family_names=list(active_specs.keys()),
            workers=workers,
        )

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

        total_cov = len(classified_slots) / max(1, len(bench_records))
        print(
            f"\nTotal Classified Tables: {len(classified_slots)} / {len(bench_records)} ({total_cov:.1%})"
        )

    # Mode: Detect Multi-Part Unions
    if args.detect_unions:
        print("\nDetecting multi-part table schedule candidates across filings...")
        from defs.taxonomy.probe.optimizer import detect_union_candidates

        union_records = query_probe_parquet(
            cache_path,
            where_clause="is_toc = false",
            columns=["doc_id", "heading", "item_label", "table_index"],
        )
        unions = detect_union_candidates(union_records)
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

        safe_sig = target_sig.replace("'", "''")
        target_records = query_probe_parquet(
            cache_path,
            where_clause=f"is_toc = false AND (lower(row_labels_text) LIKE '%{safe_sig}%' OR lower(heading) LIKE '%{safe_sig}%')",
            columns=[
                "row_labels_text",
                "heading",
                "healed_cols",
                "healed_rows",
                "numeric_density",
            ],
        )
        bg_records = query_probe_parquet(
            cache_path,
            where_clause=f"is_toc = false AND NOT (lower(row_labels_text) LIKE '%{safe_sig}%' OR lower(heading) LIKE '%{safe_sig}%')",
            columns=["row_labels_text"],
            limit=50000,
        )

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

    # Mode: Profile Table Family
    if args.profile or (
        args.family
        and not (
            args.census
            or args.discover
            or args.audit_gate
            or args.geometry
            or args.relations
            or args.inspect
            or args.benchmark
            or args.cluster_unclassified
            or args.synthesize_spec
            or args.detect_unions
            or args.export_dataset
        )
    ):
        from defs.taxonomy.probe.profiler import (
            format_profile_report,
            profile_table_family,
        )

        fam = args.family or "derivatives_hedging"
        print(f"Profiling table family '{fam}' across {cache_path}...")
        result = profile_table_family(
            cache_path=cache_path,
            family_name=fam,
            sample_jittery=args.show_jittery_samples,
        )
        report = format_profile_report(result)
        print("\n" + report)

        if args.json:
            args.json.write_text(
                json.dumps(result.to_dict(), indent=2), encoding="utf-8"
            )
            print(f"Wrote profile results to {args.json}")
        return 0

    # Mode: Export Family Dataset
    if args.export_dataset:
        if not args.family:
            print("Error: --export-dataset requires --family", file=sys.stderr)
            return 1
        print(f"Exporting family '{args.family}' dataset...")
        out = export_family_dataset(
            family=args.family,
            limit=args.limit,
            output_path=args.output_parquet,
        )
        print(f"Successfully exported dataset to {out}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
