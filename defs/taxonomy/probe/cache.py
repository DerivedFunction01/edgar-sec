"""Extract and heal HTML table grids into an atomic Parquet probe cache.

Uses the production table extraction pipeline (``span_grid`` + ``_heal_grid``)
to produce high-fidelity 2D grids, separated header vs row-stub text zones,
and post-normalization geometric properties with multi-worker parallelism and tqdm progress.
"""

from __future__ import annotations

import collections
import concurrent.futures
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import zstandard as zstd
from tqdm import tqdm

from defs.runtime.paths import resolve_paths
from defs.runtime.resources import derive_resources
from defs.sec_forms.cover.structure import parse_section_heading
from defs.storage import (
    pa,
    stream_document_blobs,
    write_table_atomic,
)
from defs.tables.table_definitions import _heal_grid
from defs.tables.templates.common import span_grid
from defs.tables.toc import looks_like_toc_text
from defs.tables.tokens import ALL_CURRENCY_SYMBOLS, is_numeric_cell
from defs.text.html import FastHtmlNode, FastHtmlTree, parse_html


def default_fixture_db_path() -> Path:
    """Resolve the canonical fixture SQLite database path from ProjectPaths."""
    project = resolve_paths()
    if project.fixtures_root.exists():
        for sql_file in project.fixtures_root.rglob("*.sqlite"):
            return sql_file
    return project.fixtures_root / "fixture.sqlite"


def probe_cache_root() -> Path:
    """Resolve the dedicated taxonomy probe cache directory under artifacts_root."""
    return resolve_paths().artifacts_root.joinpath("taxonomy", "probe")


def default_probe_cache_path(name: str | None = None) -> Path:
    """Resolve the canonical probe parquet cache path under artifacts/taxonomy/probe.

    If name is None, auto-discovers the most complete (largest/latest) existing
    parquet cache in the probe directory, or defaults to table-healed-probe.parquet.
    """
    root = probe_cache_root()
    if name is not None:
        return root / name
    if root.exists():
        candidates = sorted(
            root.glob("*.parquet"),
            key=lambda p: (p.stat().st_size, p.stat().st_mtime),
            reverse=True,
        )
        if candidates:
            return candidates[0]
    return root / "table-healed-probe.parquet"


HEAD_TAGS = frozenset(["h1", "h2", "h3", "h4", "h5", "h6"])
BOLD_TAGS = frozenset(["b", "strong"])
_DIGIT_RE = re.compile(r"\d+(?:[.,/-]\d+)*")
_WHITESPACE_RE = re.compile(r"\s+")
_FORM_RE = re.compile(r"\b(\d{1,2}-[A-Za-z]+|\d{1,2}[A-Za-z]+)\b", re.IGNORECASE)

from defs.taxonomy.probe.constants import (
    CORPORATE_BOILERPLATE,
    GRAMMAR_STOP_WORDS,
    STOP_WORDS,
    UNIT_TOKENS,
)

_dctx = zstd.ZstdDecompressor()


def decompress_payload(payload: bytes) -> str:
    """Decompress a zstd-compressed HTML document payload."""
    return _dctx.decompress(bytes(payload)).decode("utf-8", errors="replace")


def normalize_text(text: str) -> str:
    """Normalize text: lowercase, digit runs mapped to #, whitespace collapsed."""
    lowered = _DIGIT_RE.sub("#", text.casefold())
    return _WHITESPACE_RE.sub(" ", lowered).strip()


def normalize_item_label(text: str) -> str:
    """Canonicalize Item/Part headings using parse_section_heading."""
    parsed = parse_section_heading(text, allow_inline=True)
    return parsed.canonical_label if parsed is not None else ""


def detect_form_type(path: str, html: str) -> str:
    """Infer SEC form type generically from document path or lead text."""
    path_match = _FORM_RE.search(path)
    if path_match:
        return path_match.group(1).upper()
    prefix = html[:3000]
    lead_match = _FORM_RE.search(prefix)
    if lead_match:
        return lead_match.group(1).upper()
    return "UNKNOWN"


def check_column_jitter(data_rows: list[list[str]]) -> bool:
    """Check if data rows exhibit column index shifting / empty spacer jitter."""
    if len(data_rows) < 2:
        return False
    patterns: set[tuple[int, ...]] = set()
    for row in data_rows:
        if len(row) <= 1:
            continue
        data_cells = row[1:]
        indices = tuple(i for i, c in enumerate(data_cells, start=1) if c.strip())
        if indices:
            patterns.add(indices)
    return len(patterns) > 1


def check_split_affixes(grid: list[list[str]]) -> bool:
    """Check if isolated currency or paren tokens exist in cells."""
    for row in grid:
        for cell in row:
            stripped = cell.strip()
            if stripped in ALL_CURRENCY_SYMBOLS or stripped in ("(", ")", "-"):
                return True
    return False


def collect_document_tables(
    tree: FastHtmlTree,
) -> list[tuple[int, FastHtmlNode, str, str, str, str]]:
    """Walk descendants to return tables with surrounding heading & context in document order."""
    tables: list[tuple[int, FastHtmlNode, str, str, str, str]] = []
    active_item = ""
    active_heading = ""
    recent_text_blocks: collections.deque[str] = collections.deque(maxlen=3)

    for element in tree.traverse():
        name = element.tag
        if name == "table":
            if element.find_parent("table"):
                continue
            prev_context = " ".join(recent_text_blocks)
            tables.append(
                (
                    len(tables),
                    element,
                    active_item,
                    active_heading,
                    prev_context,
                    "",  # following context populated downstream
                )
            )
            continue

        is_heading_tag = name in HEAD_TAGS or name in BOLD_TAGS
        if not is_heading_tag and name not in {"div", "span", "p"}:
            continue
        if element.find_parent("table"):
            continue

        text = element.text(separator=" ", strip=True)
        if not text:
            continue

        if is_heading_tag:
            label = normalize_item_label(text)
            if label:
                active_item = label
            if len(text) < 160:
                active_heading = text
        elif len(text) < 200:
            lowered = text[:12].casefold()
            if lowered.startswith(("item ", "part ")):
                label = normalize_item_label(text)
                if label:
                    active_item = label
                    active_heading = text

        if len(text) > 20:
            recent_text_blocks.append(text[:200])

    return tables


def extract_table_record(
    doc_id: str,
    doc_path: str,
    form_type: str,
    table_idx: int,
    table_tag: FastHtmlNode | Any,
    item_label: str,
    heading: str,
    prev_context: str,
    next_context: str,
) -> dict[str, object] | None:
    """Extract, heal, and construct a structured record for one table tag."""
    raw_cells = table_tag.find_all(["td", "th"])
    if not raw_cells:
        return None

    raw_rows_tags = table_tag.find_all("tr")
    raw_rows = len(raw_rows_tags)
    raw_cols = max((len(r.find_all(["td", "th"])) for r in raw_rows_tags), default=0)
    if raw_rows == 0 or raw_cols == 0:
        return None

    full_raw_text = table_tag.get_text(" ", strip=True)
    is_toc = bool(looks_like_toc_text(full_raw_text.lower()))

    # Extract source grid with span awareness
    source_grid, span_groups = span_grid(
        table_tag,
        with_spans=True,
        join_fragmented_anchors=is_toc,
    )
    if not source_grid or not any(any(c.strip() for c in r) for r in source_grid):
        return None

    has_split = check_split_affixes(source_grid)

    # Heal grid using production pipeline
    healed_grid, header_count = _heal_grid(
        source_grid,
        debug=False,
        span_groups=span_groups,
        table=table_tag,
    )
    if not healed_grid or len(healed_grid[0]) == 0:
        healed_grid = [[c.strip() for c in r if c.strip()] for r in source_grid]
        header_count = min(1, len(healed_grid))

    healed_rows = len(healed_grid)
    healed_cols = max((len(r) for r in healed_grid), default=0)

    # Calculate post-healing numeric density
    header_rows = healed_grid[:header_count]
    data_rows = healed_grid[header_count:]
    data_cells = [c for r in data_rows for c in r if c.strip()]
    num_count = sum(1 for c in data_cells if is_numeric_cell(c))
    numeric_density = float(num_count / len(data_cells)) if data_cells else 0.0

    has_jitter = check_column_jitter(data_rows)

    # Zone-separated normalized text
    header_text_raw = " ".join(c for r in header_rows for c in r if c.strip())
    header_text = normalize_text(header_text_raw)

    row_labels_raw = " ".join(r[0] for r in data_rows if r and r[0].strip())
    row_labels_text = normalize_text(row_labels_raw)

    full_normalized = normalize_text(
        " ".join(c for r in healed_grid for c in r if c.strip())
    )
    identity_sha = hashlib.sha256(full_normalized.encode("utf-8")).hexdigest()

    return {
        "doc_id": doc_id,
        "document_path": doc_path,
        "form_type": form_type,
        "table_index": table_idx,
        "identity_sha256": identity_sha,
        "is_toc": is_toc,
        "raw_rows": raw_rows,
        "raw_cols": raw_cols,
        "healed_rows": healed_rows,
        "healed_cols": healed_cols,
        "header_count": header_count,
        "numeric_density": round(numeric_density, 4),
        "has_column_jitter": has_jitter,
        "has_split_affixes": has_split,
        "row_labels_text": row_labels_text,
        "header_text": header_text,
        "full_normalized_text": full_normalized,
        "item_label": item_label,
        "heading": heading,
        "prev_context": prev_context,
        "next_context": next_context,
        "healed_grid_json": json.dumps(healed_grid),
    }


def _process_single_blob(
    doc_id: str,
    doc_path: str,
    payload: bytes,
) -> list[dict[str, object]]:
    """Worker task: decompress payload, parse HTML, extract and heal all tables."""
    try:
        html = decompress_payload(payload)
        form_type = detect_form_type(doc_path, html)
        tree = parse_html(html)
        table_tuples = collect_document_tables(tree)

        records: list[dict[str, object]] = []
        for idx, table_tag, item_lbl, heading, prev_ctx, next_ctx in table_tuples:
            rec = extract_table_record(
                doc_id=doc_id,
                doc_path=doc_path,
                form_type=form_type,
                table_idx=idx,
                table_tag=table_tag,
                item_label=item_lbl,
                heading=heading,
                prev_context=prev_ctx,
                next_context=next_ctx,
            )
            if rec is not None:
                records.append(rec)
        return records
    except (ValueError, KeyError, TypeError, zstd.ZstdError):
        return []


def build_probe_cache_from_sqlite(
    db_path: Path | None = None,
    output_path: Path | None = None,
    limit: int = 500,
    *,
    workers: int | None = None,
    batch_size: int = 64,
) -> Path:
    """Build the healed probe parquet cache with multi-worker parallelism and tqdm progress."""
    target_db = db_path or default_fixture_db_path()
    target_out = (
        output_path
        if output_path is not None
        else probe_cache_root() / f"table-healed-probe-{limit}.parquet"
    )

    effective_workers = workers if workers is not None else derive_resources().workers
    effective_workers = max(1, effective_workers)

    all_records: list[dict[str, object]] = []
    filings_with_tables = 0
    scanned_docs = 0
    total_tables = 0

    blob_iterator = stream_document_blobs(
        target_db,
        mime_types=("text/html", "application/xhtml+xml"),
        batch_size=batch_size,
    )

    pbar = tqdm(
        total=limit,
        desc=f"Extracting tables ({effective_workers} workers)",
        unit="filing",
    )

    with concurrent.futures.ProcessPoolExecutor(
        max_workers=effective_workers
    ) as executor:
        pending_futures: dict[concurrent.futures.Future, str] = {}

        def drain_completed(stop_when_full: bool = False) -> None:
            nonlocal filings_with_tables, scanned_docs, total_tables
            for fut in list(pending_futures):
                if fut.done() or stop_when_full:
                    recs = fut.result()
                    scanned_docs += 1
                    if recs:
                        all_records.extend(recs)
                        filings_with_tables += 1
                        total_tables += len(recs)
                        pbar.update(1)
                        pbar.set_postfix(
                            {
                                "tables": total_tables,
                                "scanned": scanned_docs,
                                "hit_rate": f"{filings_with_tables / max(1, scanned_docs):.1%}",
                            }
                        )
                    del pending_futures[fut]
                    if filings_with_tables >= limit:
                        break

        for blob in blob_iterator:
            fut = executor.submit(
                _process_single_blob,
                blob.doc_id,
                blob.document_path,
                blob.raw_payload,
            )
            pending_futures[fut] = blob.doc_id

            if len(pending_futures) >= effective_workers * 4:
                # Wait for at least one future to finish before dispatching more
                done, _ = concurrent.futures.wait(
                    pending_futures.keys(),
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                for dfut in done:
                    recs = dfut.result()
                    scanned_docs += 1
                    if recs:
                        all_records.extend(recs)
                        filings_with_tables += 1
                        total_tables += len(recs)
                        pbar.update(1)
                        pbar.set_postfix(
                            {
                                "tables": total_tables,
                                "scanned": scanned_docs,
                                "hit_rate": f"{filings_with_tables / max(1, scanned_docs):.1%}",
                            }
                        )
                    del pending_futures[dfut]

            if filings_with_tables >= limit:
                break

        # Process remaining pending futures until target limit reached
        while pending_futures and filings_with_tables < limit:
            done, _ = concurrent.futures.wait(
                pending_futures.keys(),
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            for dfut in done:
                recs = dfut.result()
                scanned_docs += 1
                if recs:
                    all_records.extend(recs)
                    filings_with_tables += 1
                    total_tables += len(recs)
                    pbar.update(1)
                    pbar.set_postfix(
                        {
                            "tables": total_tables,
                            "scanned": scanned_docs,
                            "hit_rate": f"{filings_with_tables / max(1, scanned_docs):.1%}",
                        }
                    )
                del pending_futures[dfut]
                if filings_with_tables >= limit:
                    break

    pbar.close()

    if not all_records:
        raise ValueError("No table records were extracted.")

    table = pa.Table.from_pylist(all_records)
    write_table_atomic(table, target_out)
    return target_out


__all__ = [
    "CORPORATE_BOILERPLATE",
    "GRAMMAR_STOP_WORDS",
    "STOP_WORDS",
    "UNIT_TOKENS",
    "build_probe_cache_from_sqlite",
    "check_column_jitter",
    "check_split_affixes",
    "collect_document_tables",
    "decompress_payload",
    "default_fixture_db_path",
    "default_probe_cache_path",
    "detect_form_type",
    "extract_table_record",
    "normalize_item_label",
    "normalize_text",
]
