"""Family-specific Parquet dataset exporter for the taxonomy probe CLI.

Exports a dedicated queryable Parquet dataset pairing original HTML snippets,
2D healed grids, rendered ASCII output, and quality/jitter metadata for a
given table family.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from defs.runtime.paths import resolve_paths
from defs.storage import pa, stream_document_blobs, write_table_atomic
from defs.tables.builder import HTMLTableConverter
from defs.tables.templates.common import span_grid
from defs.tables.templates.dispatcher import apply_table_templates
from defs.taxonomy.probe.cache import (
    decompress_payload,
    default_fixture_db_path,
    default_probe_cache_path,
)
from defs.taxonomy.probe.rules import query_probe_parquet
from defs.taxonomy.tables.families import FAMILY_SPECS
from defs.taxonomy.tables.specs import TableFamilySpec
from defs.text.html import parse_html


def _get_family_spec(family_name: str) -> TableFamilySpec:
    spec = FAMILY_SPECS.get(family_name)
    if spec is None:
        raise ValueError(
            f"Unknown table family: '{family_name}'. "
            f"Available: {sorted(FAMILY_SPECS.keys())}"
        )
    return spec


def _build_search_terms(spec: TableFamilySpec | None) -> list[str]:
    """Extract search terms from the evidence pack for SQL filtering."""
    terms: list[str] = []
    if spec is None or spec.evidence_pack is None:
        return terms
    for tier in spec.evidence_pack.tiers:
        if tier.priority >= 5:
            for unigram in tier.unigrams:
                terms.append(re.escape(unigram))
            if tier.ngram_index:
                for ngrams in tier.ngram_index.values():
                    for ng in ngrams:
                        terms.append(re.escape(" ".join(ng)))
    return terms[:100]


def _query_family_records(
    cache_path: Path,
    family_name: str,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Query the probe parquet for tables matching the family via evidence pack."""
    spec = _get_family_spec(family_name)
    search_terms = _build_search_terms(spec)

    if search_terms:
        term_pattern = "|".join(search_terms)
        where_clause = (
            f"is_toc = false AND regexp_matches("
            f"lower(concat_ws(' ', header_text, row_labels_text)), "
            f"'(?:{term_pattern})', 'i')"
        )
    else:
        where_clause = "is_toc = false"

    records = query_probe_parquet(
        cache_path,
        where_clause=where_clause,
        limit=limit,
    )
    return records


def _fetch_html_snippets(
    records: list[dict[str, Any]],
    db_path: Path,
) -> dict[str, str]:
    """Fetch HTML content for a set of doc_ids from the blob database."""
    doc_ids = {rec["doc_id"] for rec in records}
    html_map: dict[str, str] = {}
    for blob in stream_document_blobs(db_path, limit=None):
        if blob.doc_id in doc_ids and blob.doc_id not in html_map:
            html_map[blob.doc_id] = decompress_payload(blob.raw_payload)
        if len(html_map) == len(doc_ids):
            break
    return html_map


def _reconstruct_html_from_grid(grid: list[list[str]]) -> str:
    """Reconstruct a simple HTML table from a 2D grid."""
    rows = []
    for row in grid:
        cells = "".join(f"<td>{c}</td>" for c in row)
        rows.append(f"<tr>{cells}</tr>")
    return f"<table>{''.join(rows)}</table>"


def _extract_table_html(
    html: str,
    table_index: int,
) -> str:
    """Extract the <table>...</table> snippet from parsed HTML."""
    if not html:
        return ""
    tree = parse_html(html)
    tables = tree.css("table")
    if 0 <= table_index < len(tables):
        return tables[table_index].raw_node.html
    return ""


class _DummyTableTag:
    def find_all(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []


def _generate_rendered_output(
    grid: list[list[str]],
    header_row_count: int,
    html: str = "",
) -> tuple[str, str]:
    """Render the grid using templates or HTMLTableConverter.

    Returns:
        ``(rendered_text, template_name)`` where ``template_name`` is the
        name of the matched template function (from ``TemplateResult.template_name``),
        or ``"standard_html_converter"`` when no template matched.
    """
    table: Any = _DummyTableTag()
    render_grid = grid
    if html:
        parsed = parse_html(html)
        table = parsed.find("table") or table
        if not isinstance(table, _DummyTableTag):
            render_grid, _ = span_grid(table, with_spans=True)
    res = apply_table_templates(table=table, source_grid=render_grid)
    if res:
        return res.text.strip(), res.template_name or "apply_table_templates"
    conv = (
        HTMLTableConverter(grid=render_grid, header_row_count=header_row_count)
        .to_generic_table()
        .build()
    )
    return conv.strip(), "standard_html_converter"


def export_family_dataset(
    family: str,
    *,
    cache_path: Path | None = None,
    output_path: Path | None = None,
    limit: int | None = None,
    db_path: Path | None = None,
) -> Path:
    """Export a family-specific Parquet dataset with HTML, grids, and renders.

    Args:
        family: Table family name (e.g. ``shares_purchased``).
        cache_path: Path to probe parquet cache (auto-discovered if None).
        output_path: Output parquet path (auto-discovered if None).
        limit: Maximum number of tables to export.
        db_path: Path to fixture SQLite database for HTML retrieval.

    Returns:
        The path to the written Parquet artifact.
    """
    spec = _get_family_spec(family)
    cache = cache_path or default_probe_cache_path()
    if not cache.exists():
        raise FileNotFoundError(
            f"Probe cache not found at {cache}. Use --build-cache first."
        )

    records = _query_family_records(cache, family, limit=limit)
    if not records:
        raise ValueError(f"No tables found for family '{family}'")

    db = db_path or default_fixture_db_path()

    html_map = _fetch_html_snippets(records, db)

    export_records: list[dict[str, Any]] = []
    for rec in records:
        doc_id = rec["doc_id"]
        table_index = int(rec["table_index"])
        healed_grid = json.loads(str(rec.get("healed_grid_json", "[]")))
        header_count = int(rec.get("header_count", 1))

        html_content = html_map.get(doc_id, "")
        html_snippet = _extract_table_html(html_content, table_index)
        if not html_snippet:
            html_snippet = _reconstruct_html_from_grid(healed_grid)

        rendered, template_applied = _generate_rendered_output(
            healed_grid, header_count, html_snippet
        )

        export_record: dict[str, Any] = {
            "family": family,
            "table_id": f"{doc_id}_t{table_index}",
            "doc_id": doc_id,
            "table_index": table_index,
            "document_path": rec.get("document_path", ""),
            "form_type": rec.get("form_type", "UNKNOWN"),
            "item_label": rec.get("item_label", ""),
            "heading": rec.get("heading", ""),
            "raw_rows": int(rec.get("raw_rows", 0)),
            "raw_cols": int(rec.get("raw_cols", 0)),
            "healed_rows": int(rec.get("healed_rows", 0)),
            "healed_cols": int(rec.get("healed_cols", 0)),
            "numeric_density": float(rec.get("numeric_density", 0.0)),
            "has_column_jitter": bool(rec.get("has_column_jitter", False)),
            "has_split_affixes": bool(rec.get("has_split_affixes", False)),
            "html": html_snippet,
            "healed_grid_json": json.dumps(healed_grid),
            "rendered_output": rendered,
            "template_applied": template_applied,
            "repair_policy": spec.repair_policy.value,
        }
        export_records.append(export_record)

    out = output_path or _default_output_path(family)
    out.parent.mkdir(parents=True, exist_ok=True)

    table = pa.Table.from_pylist(export_records)
    write_table_atomic(table, out)
    return out


def _default_output_path(family: str) -> Path:
    """Resolve the default output path for a family dataset."""
    project = resolve_paths()
    return project.artifacts_root.joinpath("taxonomy", "datasets", f"{family}.parquet")


__all__ = [
    "export_family_dataset",
]
