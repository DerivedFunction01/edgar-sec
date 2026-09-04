"""Empirical Table & Family Taxonomy Profiler.

Analyzes any registered TableFamilySpec against the 1.23M table probe corpus to compute
distributions for dimensions, numeric density, column headers, row labels, section contexts,
and structural jitter/repair diagnostics.
"""

from __future__ import annotations

import collections
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb

from defs.runtime.paths import resolve_paths
from defs.taxonomy.probe.cache import default_probe_cache_path
from defs.taxonomy.probe.constants import STOP_WORDS
from defs.taxonomy.probe.inspector import inspect_table_record
from defs.taxonomy.tables.families import FAMILY_SPECS

if TYPE_CHECKING:
    from defs.taxonomy.tables.specs import TableFamilySpec


@dataclass(frozen=True)
class PercentileStats:
    min: float
    p25: float
    median: float
    p75: float
    p95: float
    p99: float
    max: float


@dataclass(frozen=True)
class JitterDiagnostics:
    jitter_count: int
    jitter_pct: float
    split_affix_count: int
    split_affix_pct: float
    col_contraction_count: int
    col_contraction_pct: float
    row_compression_count: int
    row_compression_pct: float


@dataclass(frozen=True)
class FamilyProfileResult:
    family_name: str
    total_corpus_tables: int
    matched_tables: int
    match_pct: float
    form_type_distribution: dict[str, int]
    raw_rows_stats: PercentileStats
    healed_rows_stats: PercentileStats
    raw_cols_stats: PercentileStats
    healed_cols_stats: PercentileStats
    numeric_density_stats: PercentileStats
    jitter_diagnostics: JitterDiagnostics
    top_column_headers: list[dict[str, Any]]
    top_row_labels: list[dict[str, Any]]
    top_headings: list[dict[str, Any]]
    top_item_labels: list[dict[str, Any]]
    shape_constraint_violations: dict[str, Any]
    jittery_samples: list[dict[str, Any]]
    saved_sample_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _compute_percentiles(values: list[float]) -> PercentileStats:
    if not values:
        return PercentileStats(0, 0, 0, 0, 0, 0, 0)
    sorted_vals = sorted(values)
    n = len(sorted_vals)

    def pct(p: float) -> float:
        idx = int(p * (n - 1))
        return round(float(sorted_vals[idx]), 2)

    return PercentileStats(
        min=round(float(sorted_vals[0]), 2),
        p25=pct(0.25),
        median=pct(0.50),
        p75=pct(0.75),
        p95=pct(0.95),
        p99=pct(0.99),
        max=round(float(sorted_vals[-1]), 2),
    )


def _extract_frequent_lines(
    text_list: list[str], top_k: int = 30, min_len: int = 3
) -> list[dict[str, Any]]:
    """Extract and rank the most frequent raw line phrases."""
    counter: collections.Counter[str] = collections.Counter()
    total_docs = len(text_list)
    for txt in text_list:
        if not txt:
            continue
        lines = [line.strip().lower() for line in txt.split("\n")]
        # Deduplicate per table so count represents table occurrence frequency
        seen = set()
        for line in lines:
            line_clean = re.sub(r"\s+", " ", line).strip()
            if len(line_clean) >= min_len and line_clean not in STOP_WORDS:
                seen.add(line_clean)
        for item in seen:
            counter[item] += 1

    results: list[dict[str, Any]] = []
    for phrase, count in counter.most_common(top_k):
        pct = round((count / total_docs) * 100, 2) if total_docs else 0.0
        results.append({"phrase": phrase, "count": count, "pct": pct})
    return results


def profile_table_family(
    cache_path: Path | None = None,
    family_name: str = "derivatives_hedging",
    spec: TableFamilySpec | None = None,
    *,
    top_k_headers: int = 20,
    top_k_rows: int = 30,
    sample_jittery: int = 0,
) -> FamilyProfileResult:
    """Profiles a registered TableFamilySpec across the probe cache."""
    path = cache_path or default_probe_cache_path()
    if not path or not path.exists():
        raise FileNotFoundError(f"Probe parquet cache not found at: {path}")

    target_spec = spec or FAMILY_SPECS.get(family_name)
    if not target_spec:
        raise ValueError(
            f"Unknown table family: '{family_name}'. Available: {sorted(FAMILY_SPECS.keys())}"
        )

    conn = duckdb.connect()

    # Get total non-TOC tables in corpus
    total_corpus = conn.execute(
        f"SELECT count(*) FROM '{path}' WHERE is_toc = false"
    ).fetchone()[0]

    # Build initial keyword regex pattern from evidence pack primary tiers
    search_terms: list[str] = []
    if target_spec.evidence_pack:
        for tier in target_spec.evidence_pack.tiers:
            if tier.priority >= 5:
                for u in tier.unigrams:
                    search_terms.append(re.escape(u))
                if tier.ngram_index:
                    for ngrams in tier.ngram_index.values():
                        for ng in ngrams:
                            search_terms.append(re.escape(" ".join(ng)))

    # If evidence pack has primary terms, build SQL filter
    if search_terms:
        # Batch regex query in DuckDB
        term_pattern = "|".join(search_terms[:100])  # Top primary terms
        where_clause = f"""
        is_toc = false 
        AND regexp_matches(lower(concat_ws(' ', header_text, row_labels_text)), '({term_pattern})')
        """
    else:
        where_clause = "is_toc = false"

    query = f"""
    SELECT 
        doc_id, document_path, form_type, table_index, header_count,
        raw_rows, raw_cols, healed_rows, healed_cols, numeric_density,
        has_column_jitter, has_split_affixes,
        header_text, row_labels_text, heading, item_label,
        healed_grid_json
    FROM '{path}'
    WHERE {where_clause}
    """

    df = conn.execute(query).fetch_arrow_table().to_pylist()
    matched_count = len(df)
    match_pct = round((matched_count / total_corpus) * 100, 2) if total_corpus else 0.0

    # Form type distribution
    form_counter = collections.Counter(r["form_type"] for r in df if r["form_type"])
    form_dist = dict(form_counter.most_common(10))

    # Metric collections
    raw_rows = [float(r["raw_rows"]) for r in df]
    healed_rows = [float(r["healed_rows"]) for r in df]
    raw_cols = [float(r["raw_cols"]) for r in df]
    healed_cols = [float(r["healed_cols"]) for r in df]
    densities = [float(r["numeric_density"]) for r in df]

    # Jitter diagnostics
    jitter_cnt = sum(1 for r in df if r.get("has_column_jitter"))
    split_cnt = sum(1 for r in df if r.get("has_split_affixes"))
    col_contraction_cnt = sum(1 for r in df if r["raw_cols"] > r["healed_cols"])
    row_compression_cnt = sum(1 for r in df if r["raw_rows"] > r["healed_rows"])

    jitter_diag = JitterDiagnostics(
        jitter_count=jitter_cnt,
        jitter_pct=round((jitter_cnt / matched_count) * 100, 2)
        if matched_count
        else 0.0,
        split_affix_count=split_cnt,
        split_affix_pct=round((split_cnt / matched_count) * 100, 2)
        if matched_count
        else 0.0,
        col_contraction_count=col_contraction_cnt,
        col_contraction_pct=round((col_contraction_cnt / matched_count) * 100, 2)
        if matched_count
        else 0.0,
        row_compression_count=row_compression_cnt,
        row_compression_pct=round((row_compression_cnt / matched_count) * 100, 2)
        if matched_count
        else 0.0,
    )

    # Top headers, row labels, headings, and item labels
    headers_text = [r["header_text"] for r in df if r["header_text"]]
    rows_text = [r["row_labels_text"] for r in df if r["row_labels_text"]]
    headings_text = [r["heading"] for r in df if r["heading"]]
    items_text = [r["item_label"] for r in df if r["item_label"]]

    top_headers = _extract_frequent_lines(headers_text, top_k=top_k_headers, min_len=3)
    top_rows = _extract_frequent_lines(rows_text, top_k=top_k_rows, min_len=3)
    top_headings = _extract_frequent_lines(headings_text, top_k=15, min_len=4)
    top_items = _extract_frequent_lines(items_text, top_k=10, min_len=2)

    # Shape constraint check
    shape = target_spec.shape
    violating_tables = 0
    for r in df:
        h_rows = int(r["healed_rows"])
        h_cols = int(r["healed_cols"])
        dens = float(r["numeric_density"])
        if (
            h_rows < shape.min_rows
            or (shape.max_rows is not None and h_rows > shape.max_rows)
            or h_cols < shape.min_cols
            or (shape.max_cols is not None and h_cols > shape.max_cols)
            or dens < shape.min_numeric_density
        ):
            violating_tables += 1

    shape_violations = {
        "spec_shape": {
            "min_rows": shape.min_rows,
            "max_rows": shape.max_rows,
            "min_cols": shape.min_cols,
            "max_cols": shape.max_cols,
            "min_numeric_density": shape.min_numeric_density,
        },
        "violating_count": violating_tables,
        "violating_pct": round((violating_tables / matched_count) * 100, 2)
        if matched_count
        else 0.0,
    }

    # Sample jittery tables if requested
    jittery_samples: list[dict[str, Any]] = []
    saved_sample_path: str | None = None
    if sample_jittery > 0:
        jittery_rows = [
            r for r in df if r.get("has_column_jitter") or r.get("has_split_affixes")
        ]
        sample_records = jittery_rows[:sample_jittery]
        for item in sample_records:
            grid_raw = item.get("healed_grid_json")
            grid = json.loads(grid_raw) if grid_raw else []
            jittery_samples.append(
                {
                    "doc_id": item["doc_id"],
                    "form_type": item["form_type"],
                    "table_index": item["table_index"],
                    "raw_shape": (item["raw_rows"], item["raw_cols"]),
                    "healed_shape": (item["healed_rows"], item["healed_cols"]),
                    "heading": item["heading"],
                    "grid_preview": grid[:5],
                }
            )
        if sample_records:
            saved_p = save_sample_renders(sample_records, family_name=family_name)
            saved_sample_path = str(saved_p)

    return FamilyProfileResult(
        family_name=family_name,
        total_corpus_tables=total_corpus,
        matched_tables=matched_count,
        match_pct=match_pct,
        form_type_distribution=form_dist,
        raw_rows_stats=_compute_percentiles(raw_rows),
        healed_rows_stats=_compute_percentiles(healed_rows),
        raw_cols_stats=_compute_percentiles(raw_cols),
        healed_cols_stats=_compute_percentiles(healed_cols),
        numeric_density_stats=_compute_percentiles(densities),
        jitter_diagnostics=jitter_diag,
        top_column_headers=top_headers,
        top_row_labels=top_rows,
        top_headings=top_headings,
        top_item_labels=top_items,
        shape_constraint_violations=shape_violations,
        jittery_samples=jittery_samples,
        saved_sample_path=saved_sample_path,
    )


def probe_samples_root(family_name: str) -> Path:
    """Resolve the dedicated taxonomy samples directory for a family under artifacts_root."""
    return resolve_paths().artifacts_root.joinpath("taxonomy", "samples", family_name)


def save_sample_renders(
    records: list[dict[str, Any]],
    family_name: str,
    output_dir: Path | None = None,
) -> Path:
    """Renders table diagnostic records to a timestamped file and returns the saved file path."""
    target_dir = (
        output_dir if output_dir is not None else probe_samples_root(family_name)
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    sample_file = target_dir / f"samples_{family_name}_{timestamp}.txt"

    lines: list[str] = [
        "=" * 80,
        f" TABLE RENDER SAMPLES FOR FAMILY: {family_name.upper()} ",
        f" Timestamp: {timestamp} | Total Samples: {len(records)}",
        "=" * 80,
        "",
    ]

    for idx, rec in enumerate(records, 1):
        lines.append(f"################### SAMPLE #{idx:02d} ###################")
        lines.append(inspect_table_record(rec, test_templates=True))
        lines.append("\n" + "=" * 80 + "\n")

    sample_file.write_text("\n".join(lines), encoding="utf-8")
    return sample_file


def format_profile_report(result: FamilyProfileResult) -> str:
    """Formats the profile result into a readable report."""
    lines: list[str] = [
        "=" * 80,
        f" EMPIRICAL TABLE FAMILY PROFILE: {result.family_name.upper()} ",
        "=" * 80,
        f"Corpus Tables:   {result.total_corpus_tables:,} non-TOC tables",
        f"Matched Tables:  {result.matched_tables:,} ({result.match_pct:.2f}% of corpus)",
        f"Form Types:      {', '.join(f'{k}: {v:,}' for k, v in result.form_type_distribution.items())}",
    ]
    if result.saved_sample_path:
        lines.append(f"Saved Samples:   {result.saved_sample_path}")
    lines.extend(
        [
            "",
            "--- 1. 2D SHAPE & DIMENSIONS ---",
            f"{'Metric':<18} | {'Min':<6} | {'P25':<6} | {'Median':<6} | {'P75':<6} | {'P95':<6} | {'P99':<6} | {'Max':<6}",
            "-" * 80,
            f"{'Raw Rows':<18} | {result.raw_rows_stats.min:<6} | {result.raw_rows_stats.p25:<6} | {result.raw_rows_stats.median:<6} | {result.raw_rows_stats.p75:<6} | {result.raw_rows_stats.p95:<6} | {result.raw_rows_stats.p99:<6} | {result.raw_rows_stats.max:<6}",
            f"{'Healed Rows':<18} | {result.healed_rows_stats.min:<6} | {result.healed_rows_stats.p25:<6} | {result.healed_rows_stats.median:<6} | {result.healed_rows_stats.p75:<6} | {result.healed_rows_stats.p95:<6} | {result.healed_rows_stats.p99:<6} | {result.healed_rows_stats.max:<6}",
            f"{'Raw Columns':<18} | {result.raw_cols_stats.min:<6} | {result.raw_cols_stats.p25:<6} | {result.raw_cols_stats.median:<6} | {result.raw_cols_stats.p75:<6} | {result.raw_cols_stats.p95:<6} | {result.raw_cols_stats.p99:<6} | {result.raw_cols_stats.max:<6}",
            f"{'Healed Columns':<18} | {result.healed_cols_stats.min:<6} | {result.healed_cols_stats.p25:<6} | {result.healed_cols_stats.median:<6} | {result.healed_cols_stats.p75:<6} | {result.healed_cols_stats.p95:<6} | {result.healed_cols_stats.p99:<6} | {result.healed_cols_stats.max:<6}",
            f"{'Numeric Density':<18} | {result.numeric_density_stats.min:<6} | {result.numeric_density_stats.p25:<6} | {result.numeric_density_stats.median:<6} | {result.numeric_density_stats.p75:<6} | {result.numeric_density_stats.p95:<6} | {result.numeric_density_stats.p99:<6} | {result.numeric_density_stats.max:<6}",
            "",
            "--- 2. JITTER & STRUCTURAL REPAIR DIAGNOSTICS ---",
            f"Column Jitter Rate:    {result.jitter_diagnostics.jitter_count:,} tables ({result.jitter_diagnostics.jitter_pct:.2f}%)",
            f"Split Affixes ($/%) :   {result.jitter_diagnostics.split_affix_count:,} tables ({result.jitter_diagnostics.split_affix_pct:.2f}%)",
            f"Column Contraction:    {result.jitter_diagnostics.col_contraction_count:,} tables ({result.jitter_diagnostics.col_contraction_pct:.2f}%) [raw_cols > healed_cols]",
            f"Row Consolidation:     {result.jitter_diagnostics.row_compression_count:,} tables ({result.jitter_diagnostics.row_compression_pct:.2f}%) [raw_rows > healed_rows]",
            f"Shape Violations:      {result.shape_constraint_violations['violating_count']:,} candidate tables ({result.shape_constraint_violations['violating_pct']:.2f}%) pruned by active ShapeConstraint",
            "",
            "--- 3. TOP COLUMN HEADERS ---",
        ]
    )
    for idx, hdr in enumerate(result.top_column_headers[:15], 1):
        lines.append(
            f"  {idx:>2}. {hdr['phrase']:<50} | {hdr['count']:>6,} ({hdr['pct']:>5.2f}%)"
        )

    lines.extend(["", "--- 4. TOP ROW LABELS / LINE ITEMS ---"])
    for idx, row in enumerate(result.top_row_labels[:20], 1):
        lines.append(
            f"  {idx:>2}. {row['phrase']:<50} | {row['count']:>6,} ({row['pct']:>5.2f}%)"
        )

    lines.extend(["", "--- 5. TOP SECTION / NOTE HEADINGS ---"])
    for idx, hdg in enumerate(result.top_headings[:8], 1):
        lines.append(
            f"  {idx:>2}. {hdg['phrase']:<50} | {hdg['count']:>6,} ({hdg['pct']:>5.2f}%)"
        )

    lines.append("=" * 80)
    return "\n".join(lines)


__all__ = [
    "FamilyProfileResult",
    "JitterDiagnostics",
    "PercentileStats",
    "format_profile_report",
    "profile_table_family",
]
