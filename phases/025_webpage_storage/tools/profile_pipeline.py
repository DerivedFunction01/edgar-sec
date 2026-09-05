"""Fine-grained profiling tool for Phase 025 document normalization pipeline."""

from __future__ import annotations

import argparse
import html
import json
import re
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from tqdm import tqdm

from defs.regex import build_alternation
from defs.sec_forms.cover import (
    BoundaryInput,
    find_body_start,
    find_closing_span,
    find_cover_boundary_for_profile,
    find_toc_span,
    get_profile,
)
from defs.sec_forms.page_markers import (
    analyze_page_markers,
    apply_html_page_decisions,
    enrich_html_analysis,
    extract_ascii_pre,
    refresh_html_analysis,
    strip_page_markers,
)
from defs.storage import atomic_write_text
from defs.tables import convert_html_tables_to_ascii
from defs.text.html import parse_html
from defs.text.reflow import reflow_ascii

from ..core.schemas import DocumentLocator, decompress_payload, doc_id
from ..processors.forms.base import PreprocessedDocument
from ..processors.preprocessor import (
    _RE_DOCUMENT_WRAPPER,
    _RE_HEAD_SCRIPT_STYLE,
    _RE_HTML_DISCRIMINATOR,
    GenericPreprocessor,
)
from ..processors.router import FormRouter
from ..testing.corpus import find_document_cases
from ..testing.paths import fixture_paths
from .promote_document_corpus import _load_fixture_manifest, build_records

_IXBRL_PREFIXES = build_alternation(["ix", "xbrli", "dei", "us-gaap"])
_RE_XML_IXBRL_TAGS = re.compile(rf"</?(?:{_IXBRL_PREFIXES}):[^>]*>", re.IGNORECASE)
_RE_TABLE_TAG = re.compile(r"<\/?table\b", re.IGNORECASE)
_RE_MULTIPLE_BLANKS = re.compile(r"\n{3,}")
_RE_TRAILING_WHITESPACE = re.compile(r"[ \t]+$", re.MULTILINE)


@dataclass
class DocumentProfile:
    doc_id: str
    form: str
    extension: str
    representation: str
    raw_size_bytes: int
    line_count: int
    word_count: int
    timings_ms: dict[str, float]
    total_time_ms: float


def profile_single_document(
    record: dict[str, Any],
    router: FormRouter,
    verbose: bool = False,
) -> DocumentProfile:
    timings: dict[str, float] = {}
    doc_identifier = str(record.get("doc_id") or record.get("document_id") or "")[:16]

    def vprint(msg: str) -> None:
        if verbose:
            print(f"[{doc_identifier}] {msg}", flush=True)

    vprint("--- Starting profile ---")
    vprint("Step 1: Decompress payload...")
    t0 = time.perf_counter()
    if record.get("raw_payload") is not None:
        raw_payload = record["raw_payload"]
        if isinstance(raw_payload, (bytes, bytearray, memoryview)):
            raw_bytes = decompress_payload(bytes(raw_payload))
        else:
            raw_bytes = str(raw_payload).encode("utf-8")
    elif record.get("source_bytes") is not None:
        raw_bytes = bytes(record["source_bytes"])
    else:
        raw_bytes = b""
    t1 = time.perf_counter()
    timings["decompress"] = (t1 - t0) * 1000.0

    raw_size = len(raw_bytes)
    form = str(record.get("form") or "")
    path_str = str(record.get("document_path") or record.get("document_id") or "")
    ext = Path(path_str).suffix.lower() or ".txt"

    # Stage 2: Preprocess - Decoding
    vprint(f"Step 2: Decode bytes ({raw_size} bytes)...")
    t0 = time.perf_counter()
    raw_text, encoding = GenericPreprocessor.decode_bytes(raw_bytes)
    t1 = time.perf_counter()
    timings["preprocess_decode"] = (t1 - t0) * 1000.0

    # Stage 3: Preprocess - Envelope & Script/Style Stripping
    vprint(f"Step 3: Strip tags & envelope ({len(raw_text)} chars)...")
    t0 = time.perf_counter()
    m_doc = _RE_DOCUMENT_WRAPPER.match(raw_text.strip())
    content_text = m_doc.group(1) if m_doc else raw_text
    clean = _RE_HEAD_SCRIPT_STYLE.sub(" ", content_text)
    clean = html.unescape(clean)

    ascii_pre = extract_ascii_pre(clean)
    has_html = bool(_RE_HTML_DISCRIMINATOR.search(clean)) and ascii_pre is None
    if ascii_pre is not None:
        clean = ascii_pre
        representation = "ascii"
    else:
        representation = "html" if has_html else "ascii"
    t1 = time.perf_counter()
    timings["preprocess_clean_tags"] = (t1 - t0) * 1000.0

    # Stage 4: Preprocess - Initial Page Marker Analysis
    vprint(
        f"Step 4: Analyze page markers (repr={representation}, {len(clean)} chars)..."
    )
    t0 = time.perf_counter()
    words = clean.split()
    word_count = len(words)
    page_analysis = analyze_page_markers(clean, representation=representation)
    t1 = time.perf_counter()
    timings["preprocess_page_analysis"] = (t1 - t0) * 1000.0

    preprocessed = PreprocessedDocument(
        raw_text=raw_text,
        cleaned_text=clean,
        word_count=word_count,
        has_html_tags=has_html,
        detected_encoding=encoding,
        metadata={"form": form, "representation": representation},
        page_analysis=page_analysis,
        representation=representation,
    )

    # Stage 5: Router Evaluation
    vprint("Step 5: Router evaluate...")
    t0 = time.perf_counter()
    locator = DocumentLocator(
        locator_key=f"{record.get('accession')}:{record.get('document_path')}",
        accession=str(record.get("accession") or ""),
        document_path=str(record.get("document_path") or ""),
        archive_url=str(record.get("archive_url") or ""),
        form=form,
    )
    _ = router.evaluate(preprocessed, locator)
    form_normalizer = router.get_normalizer(form)
    profile = get_profile(form)
    t1 = time.perf_counter()
    timings["router_evaluate"] = (t1 - t0) * 1000.0

    # Stage 6: Normalization
    is_html = representation == "html" or preprocessed.has_html_tags
    text = preprocessed.cleaned_text

    # 6a. HTML DOM parsing & enrichment (HTML only)
    if is_html:
        vprint("Step 6a: Parse HTML DOM & enrich page decisions...")
        t0 = time.perf_counter()
        tree = parse_html(text)
        page_analysis = enrich_html_analysis(page_analysis, tree, source_text=text)
        if apply_html_page_decisions(tree, page_analysis):
            text = str(tree)
            page_analysis = refresh_html_analysis(page_analysis, text)
        t1 = time.perf_counter()
        timings["html_dom_parse_enrich"] = (t1 - t0) * 1000.0
    else:
        timings["html_dom_parse_enrich"] = 0.0

    # 6b. Cover Boundary Detection
    vprint("Step 6b: Detect cover boundary...")
    t0 = time.perf_counter()
    boundary = find_cover_boundary_for_profile(
        BoundaryInput(
            text,
            representation=representation,
            page_analysis=page_analysis,
        ),
        profile,
    )
    t1 = time.perf_counter()
    timings["cover_boundary_detect"] = (t1 - t0) * 1000.0

    # 6c. Cover Preprocessing
    if is_html and bool(_RE_TABLE_TAG.search(text)):
        vprint("Step 6c: Preprocess HTML cover...")
        t0 = time.perf_counter()
        cover_result = form_normalizer.preprocess_cover(
            text, {"form": form}, page_analysis=page_analysis
        )
        text = cover_result.html
        page_analysis = refresh_html_analysis(page_analysis, text)
        boundary = find_cover_boundary_for_profile(
            BoundaryInput(
                text,
                representation=representation,
                page_analysis=page_analysis,
            ),
            profile,
        )
        t1 = time.perf_counter()
        timings["cover_preprocess"] = (t1 - t0) * 1000.0
    else:
        timings["cover_preprocess"] = 0.0

    # 6d. HTML Tables to ASCII conversion
    if is_html and bool(_RE_HTML_DISCRIMINATOR.search(text)):
        vprint("Step 6d: Convert HTML tables to ASCII...")
        t0 = time.perf_counter()
        text = convert_html_tables_to_ascii(text)
        page_analysis = refresh_html_analysis(page_analysis, text)
        t1 = time.perf_counter()
        timings["html_table_ascii_convert"] = (t1 - t0) * 1000.0
    else:
        timings["html_table_ascii_convert"] = 0.0

    # 6e. Strip Page Markers & Tag Sub
    vprint("Step 6e: Strip page markers & tags...")
    t0 = time.perf_counter()
    cleaned_text = _RE_XML_IXBRL_TAGS.sub("", text)
    if cleaned_text != text:
        text = cleaned_text
        if is_html:
            page_analysis = refresh_html_analysis(page_analysis, text)
    text = strip_page_markers(text, page_analysis)
    if is_html:
        page_analysis = refresh_html_analysis(page_analysis, text)
    t1 = time.perf_counter()
    timings["strip_page_markers"] = (t1 - t0) * 1000.0

    # 6f. Header Normalization & Whitespace Cleanup
    vprint("Step 6f: Normalize headers & cleanup whitespace...")
    t0 = time.perf_counter()
    text = form_normalizer.normalize_headers(text, {"form": form})
    text = _RE_TRAILING_WHITESPACE.sub("", text)
    text = _RE_MULTIPLE_BLANKS.sub("\n\n", text)
    t1 = time.perf_counter()
    timings["normalize_headers_whitespace"] = (t1 - t0) * 1000.0

    # 6g. Table of Contents & Body Start Detection
    vprint("Step 6g: Find TOC & Body Start...")
    t0 = time.perf_counter()
    body_start = None
    toc_span = None
    if profile.boundary is not None and profile.body_evidence is not None:
        toc_span = find_toc_span(
            text,
            start_line=boundary.start_line or 0,
            page_analysis=page_analysis,
            derived_taxonomy=profile.derived_taxonomy,
        )
        body_start = find_body_start(
            text,
            cover_end=boundary.end_line,
            toc_end=toc_span.end_line if toc_span is not None else None,
            evidence=profile.body_evidence,
            toc_span=toc_span,
        )
    t1 = time.perf_counter()
    timings["find_toc_and_body_start"] = (t1 - t0) * 1000.0

    # 6h. ASCII Reflow
    if (
        not is_html
        and body_start is not None
        and body_start.first_unit_line is not None
    ):
        vprint("Step 6h: ASCII Reflow...")
        t0 = time.perf_counter()
        reflow_result = reflow_ascii(
            text,
            body_start_line=body_start.first_unit_line,
            page_analysis=page_analysis,
        )
        text = reflow_result.text
        t1 = time.perf_counter()
        timings["ascii_reflow"] = (t1 - t0) * 1000.0
    else:
        timings["ascii_reflow"] = 0.0

    # 6i. Closing Span Detection
    if body_start is not None and body_start.first_unit_line is not None:
        vprint("Step 6i: Find closing span...")
        t0 = time.perf_counter()
        _ = find_closing_span(text, search_from=body_start.first_unit_line + 1)
        t1 = time.perf_counter()
        timings["find_closing_span"] = (t1 - t0) * 1000.0
    else:
        timings["find_closing_span"] = 0.0

    total_time = sum(timings.values())
    line_count = len(text.splitlines())
    vprint(f"--- Finished in {total_time:.1f}ms ---\n")

    return DocumentProfile(
        doc_id=str(
            record.get("document_id")
            or doc_id(locator.accession, locator.document_path)
        ),
        form=form,
        extension=ext,
        representation=representation,
        raw_size_bytes=raw_size,
        line_count=line_count,
        word_count=word_count,
        timings_ms=timings,
        total_time_ms=total_time,
    )


def summarize_profiles(profiles: list[DocumentProfile]) -> dict[str, Any]:
    if not profiles:
        return {}

    stage_totals: dict[str, float] = defaultdict(float)
    format_totals: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "total_time_ms": 0.0, "stages": defaultdict(float)}
    )

    total_time_all = sum(p.total_time_ms for p in profiles)

    for p in profiles:
        fmt = f"{p.representation} ({p.extension})"
        format_totals[fmt]["count"] += 1
        format_totals[fmt]["total_time_ms"] += p.total_time_ms

        for stage, t in p.timings_ms.items():
            stage_totals[stage] += t
            format_totals[fmt]["stages"][stage] += t

    ranking = sorted(
        [
            {
                "stage": stage,
                "total_time_ms": round(t, 2),
                "avg_per_doc_ms": round(t / len(profiles), 2),
                "pct_of_total": round(
                    (t / total_time_all * 100.0) if total_time_all else 0, 2
                ),
            }
            for stage, t in stage_totals.items()
        ],
        key=lambda x: x["total_time_ms"],
        reverse=True,
    )

    format_summaries = {}
    for fmt, data in format_totals.items():
        cnt = data["count"]
        tot = data["total_time_ms"]
        format_summaries[fmt] = {
            "count": cnt,
            "total_time_ms": round(tot, 2),
            "avg_time_per_doc_ms": round(tot / cnt, 2) if cnt else 0,
            "top_stages": sorted(
                [
                    {
                        "stage": s,
                        "avg_ms": round(st / cnt, 2),
                        "pct": round(st / tot * 100, 2) if tot else 0,
                    }
                    for s, st in data["stages"].items()
                ],
                key=lambda x: x["avg_ms"],
                reverse=True,
            )[:5],
        }

    return {
        "document_count": len(profiles),
        "total_wall_time_ms": round(total_time_all, 2),
        "avg_time_per_doc_ms": round(total_time_all / len(profiles), 2),
        "docs_per_second_single_core": round(
            len(profiles) / (total_time_all / 1000.0) if total_time_all else 0, 2
        ),
        "stage_bottlenecks": ranking,
        "format_breakdown": format_summaries,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture-id")
    source.add_argument("--corpus", type=Path)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--extension", "--ext", action="append", default=[])
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="disable the tqdm progress bar",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="print fine-grained step-by-step debug timings per document",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    extensions = list(args.extension) if args.extension else None
    if args.fixture_id:
        paths = fixture_paths(args.fixture_id)
        _load_fixture_manifest(paths)
        records = build_records(
            paths,
            limit=args.limit,
            extensions=extensions,
        )
    else:
        selected = find_document_cases(
            extensions=extensions,
            path=args.corpus,
        )
        records = selected[: args.limit] if args.limit else selected

    router = FormRouter()
    profiles: list[DocumentProfile] = []

    progress_bar = tqdm(
        records,
        desc="Profiling documents",
        unit="docs",
        disable=args.no_progress or args.verbose,
    )
    for record in progress_bar:
        p = profile_single_document(record, router, verbose=args.verbose)
        profiles.append(p)
        if not args.verbose:
            progress_bar.set_postfix(
                doc=p.doc_id[:8],
                ext=p.extension,
                lines=p.line_count,
                time=f"{p.total_time_ms:.0f}ms",
            )

    summary = summarize_profiles(profiles)

    print("\n" + "=" * 80, flush=True)
    print("PIPELINE STAGE BOTTLENECK RANKING (All Documents)", flush=True)
    print("=" * 80, flush=True)
    print(
        f"{'Stage':<35} | {'Avg (ms)':<10} | {'Total (s)':<10} | {'% of Time':<10}",
        flush=True,
    )
    print("-" * 80, flush=True)
    for row in summary.get("stage_bottlenecks", []):
        print(
            f"{row['stage']:<35} | {row['avg_per_doc_ms']:<10.2f} | {row['total_time_ms'] / 1000:<10.2f} | {row['pct_of_total']:<10.1f}%",
            flush=True,
        )
    print("=" * 80, flush=True)

    print("\nFORMAT BREAKDOWN:", flush=True)
    for fmt, data in summary.get("format_breakdown", {}).items():
        print(
            f"\n* Format: {fmt} (N={data['count']}, Avg = {data['avg_time_per_doc_ms']:.1f}ms/doc)",
            flush=True,
        )
        for st in data["top_stages"]:
            print(
                f"    - {st['stage']:<30}: {st['avg_ms']:>8.2f}ms ({st['pct']:>5.1f}%)",
                flush=True,
            )

    report_payload = {
        "summary": summary,
        "profiles": [asdict(p) for p in profiles],
    }

    if args.output:
        atomic_write_text(args.output, json.dumps(report_payload, indent=2))
        print(f"\nDetailed report saved to: {args.output}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
