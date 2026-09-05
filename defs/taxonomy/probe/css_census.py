"""Efficient empirical census of table HTML/CSS features.

Scans compressed fixture documents with selectolax and writes aggregate
feature frequencies plus bounded per-table records. It intentionally does not
attempt CSS layout or rendering; it inventories the evidence needed by the
separate geometry-renderer experiment.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from selectolax.parser import HTMLParser, Node

from defs.storage import pa, stream_document_blobs, write_table_atomic
from defs.taxonomy.probe.cache import decompress_payload, default_fixture_db_path

_STYLE_DECL_RE = re.compile(r"(?:^|;)\s*([\w-]+)\s*:", re.IGNORECASE)
_CLASS_TOKEN_RE = re.compile(r"[^\s]+")


@dataclass
class _Counts:
    documents: int = 0
    tables: int = 0
    rows: int = 0
    cells: int = 0
    empty_cells: int = 0
    nested_tables: int = 0
    table_attrs: Counter[str] = field(default_factory=Counter)
    cell_attrs: Counter[str] = field(default_factory=Counter)
    tags: Counter[str] = field(default_factory=Counter)
    style_properties: Counter[str] = field(default_factory=Counter)
    style_values: Counter[str] = field(default_factory=Counter)
    classes: Counter[str] = field(default_factory=Counter)
    ids: Counter[str] = field(default_factory=Counter)
    attr_values: Counter[str] = field(default_factory=Counter)
    css_rules: int = 0
    css_properties: Counter[str] = field(default_factory=Counter)


def _record_attrs(node: Node, counts: _Counts, *, table: bool) -> None:
    attrs = counts.table_attrs if table else counts.cell_attrs
    for name, value in node.attributes.items():
        value = value or ""
        attrs[name.casefold()] += 1
        if name.casefold() == "style":
            for prop in _STYLE_DECL_RE.findall(value):
                prop = prop.casefold()
                counts.style_properties[prop] += 1
                counts.style_values[f"{prop}={value.strip()}"] += 1
        elif name.casefold() == "class":
            counts.classes.update(_CLASS_TOKEN_RE.findall(value))
        elif name.casefold() == "id":
            counts.ids[value] += 1
        elif name.casefold() in {
            "align",
            "valign",
            "display",
            "width",
            "height",
            "border",
            "cellpadding",
            "cellspacing",
            "nowrap",
        }:
            counts.attr_values[f"{name.casefold()}={value.strip()}"] += 1


def _scan_style_blocks(tree: HTMLParser, counts: _Counts) -> None:
    for style in tree.css("style"):
        text = style.text(separator=" ") or ""
        counts.css_rules += max(0, text.count("{"))
        for prop in _STYLE_DECL_RE.findall(text):
            counts.css_properties[prop.casefold()] += 1


def _table_record(node: Node, doc_id: str, index: int) -> dict[str, Any]:
    rows = node.css("tr")
    cells = [cell for row in rows for cell in row.css("td,th")]
    styles = Counter()
    tags = Counter()
    for child in node.traverse():
        tags[child.tag] += 1
        style = child.attributes.get("style", "") or ""
        styles.update(prop.casefold() for prop in _STYLE_DECL_RE.findall(style))
    return {
        "doc_id": doc_id,
        "table_index": index,
        "raw_rows": len(rows),
        "raw_cells": len(cells),
        "empty_cells": sum(
            not (cell.text(separator=" ") or "").strip() for cell in cells
        ),
        "nested_tables": max(0, len(node.css("table")) - 1),
        "table_attributes_json": json.dumps(sorted(node.attributes)),
        "style_properties_json": json.dumps(dict(styles)),
        "tags_json": json.dumps(dict(tags)),
    }


def _scan_document(
    doc_id: str, payload: bytes, sample_limit: int
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Worker: decompress and census one document without retaining HTML."""
    counts = _Counts(documents=1)
    samples: list[dict[str, Any]] = []
    tree = HTMLParser(decompress_payload(payload))
    _scan_style_blocks(tree, counts)
    for index, table in enumerate(tree.css("table")):
        counts.tables += 1
        _record_attrs(table, counts, table=True)
        rows = table.css("tr")
        counts.rows += len(rows)
        cells = [cell for row in rows for cell in row.css("td,th")]
        counts.cells += len(cells)
        counts.empty_cells += sum(
            not (cell.text(separator=" ") or "").strip() for cell in cells
        )
        counts.nested_tables += max(0, len(table.css("table")) - 1)
        for child in table.traverse():
            counts.tags[child.tag] += 1
        for cell in cells:
            _record_attrs(cell, counts, table=False)
        if len(samples) < sample_limit:
            samples.append(_table_record(table, doc_id, index))
    return _counts_dict(counts), samples


def _counts_dict(counts: _Counts) -> dict[str, Any]:
    return {
        "documents": counts.documents,
        "tables": counts.tables,
        "rows": counts.rows,
        "cells": counts.cells,
        "empty_cells": counts.empty_cells,
        "nested_tables": counts.nested_tables,
        "css_rules": counts.css_rules,
        "table_attributes": dict(counts.table_attrs),
        "cell_attributes": dict(counts.cell_attrs),
        "tags": dict(counts.tags),
        "style_properties": dict(counts.style_properties),
        "style_values": dict(counts.style_values),
        "classes": dict(counts.classes),
        "ids": dict(counts.ids),
        "attribute_values": dict(counts.attr_values),
        "stylesheet_properties": dict(counts.css_properties),
    }


def _merge_counts(target: _Counts, source: dict[str, Any]) -> None:
    for field_name in (
        "documents",
        "tables",
        "rows",
        "cells",
        "empty_cells",
        "nested_tables",
        "css_rules",
    ):
        setattr(target, field_name, getattr(target, field_name) + source[field_name])
    for source_name, target_name in (
        ("table_attributes", "table_attrs"),
        ("cell_attributes", "cell_attrs"),
        ("tags", "tags"),
        ("style_properties", "style_properties"),
        ("style_values", "style_values"),
        ("classes", "classes"),
        ("ids", "ids"),
        ("attribute_values", "attr_values"),
        ("stylesheet_properties", "css_properties"),
    ):
        getattr(target, target_name).update(source[source_name])


def census_documents(
    *,
    db_path: Path | None = None,
    limit: int | None = None,
    sample_limit: int = 5000,
    workers: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Scan fixture documents once and return aggregate counts and samples."""
    counts = _Counts()
    samples: list[dict[str, Any]] = []
    db = db_path or default_fixture_db_path()
    worker_count = workers or max(1, (os.cpu_count() or 2) - 1)
    pending: set[Any] = set()

    def collect(done: set[Any]) -> None:
        for future in done:
            summary, document_samples = future.result()
            _merge_counts(counts, summary)
            if len(samples) < sample_limit:
                samples.extend(document_samples[: sample_limit - len(samples)])

    with ProcessPoolExecutor(max_workers=worker_count) as pool:
        for blob in stream_document_blobs(db, limit=limit):
            pending.add(
                pool.submit(_scan_document, blob.doc_id, blob.raw_payload, sample_limit)
            )
            if len(pending) >= worker_count * 2:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                collect(done)
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            collect(done)

    summary = _counts_dict(counts)
    for key in ("style_values", "classes", "ids", "attribute_values"):
        summary[key] = dict(Counter(summary[key]).most_common(500))
    return summary, samples


def write_census(
    summary: dict[str, Any], samples: list[dict[str, Any]], output: Path
) -> None:
    """Write JSON summary and adjacent Parquet table samples."""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"summary": summary, "sample_count": len(samples)}, indent=2) + "\n",
        encoding="utf-8",
    )
    sample_path = output.with_suffix(".parquet")
    write_table_atomic(pa.Table.from_pylist(samples), sample_path)


__all__ = ["census_documents", "write_census"]
