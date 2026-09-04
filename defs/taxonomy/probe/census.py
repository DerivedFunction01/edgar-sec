"""Cross-firm vocabulary census, n-gram mining, term distinctiveness, and unclassified table clustering."""

from __future__ import annotations

import collections
import re
import statistics
from typing import TYPE_CHECKING, Any

from defs.taxonomy.probe.cache import STOP_WORDS

if TYPE_CHECKING:
    from collections.abc import Sequence

_TOKEN_RE = re.compile(r"[a-z]+(?:'[a-z]+)?|#")


def extract_ngrams(
    text: str, n: int = 1, *, stop_words: frozenset[str] = STOP_WORDS
) -> list[str]:
    """Extract filtered content-word n-grams from normalized text."""
    tokens = [t for t in _TOKEN_RE.findall(text.lower()) if t not in stop_words]
    if len(tokens) < n:
        return []
    return [" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def extract_all_ngrams(
    text: str,
    *,
    min_n: int = 1,
    max_n: int = 3,
    stop_words: frozenset[str] = STOP_WORDS,
) -> list[str]:
    """Extract all n-grams across a range of orders [min_n..max_n]."""
    all_grams: list[str] = []
    for n in range(min_n, max_n + 1):
        all_grams.extend(extract_ngrams(text, n=n, stop_words=stop_words))
    return all_grams


def census_vocabulary(
    records: Sequence[dict[str, Any]],
    *,
    n: int = 1,
    zone: str = "row_labels",
    top_k: int = 50,
    min_doc_count: int = 3,
    stop_words: frozenset[str] = STOP_WORDS,
) -> list[dict[str, object]]:
    """Compute corpus-wide vocabulary census for a given zone (row_labels, header, or full)."""
    term_counts: collections.Counter[str] = collections.Counter()
    doc_counts: collections.Counter[str] = collections.Counter()

    zone_key = {
        "row_labels": "row_labels_text",
        "headers": "header_text",
        "header": "header_text",
        "full": "full_normalized_text",
    }.get(zone, "row_labels_text")

    total_records = len(records) or 1

    for rec in records:
        text = str(rec.get(zone_key, ""))
        grams = extract_ngrams(text, n=n, stop_words=stop_words)
        term_counts.update(grams)
        doc_counts.update(set(grams))

    results: list[dict[str, object]] = []
    for term, d_cnt in doc_counts.items():
        if d_cnt < min_doc_count:
            continue
        total_occurrences = term_counts[term]
        doc_freq = d_cnt / total_records
        results.append(
            {
                "term": term,
                "doc_count": d_cnt,
                "total_occurrences": total_occurrences,
                "doc_frequency": round(doc_freq, 4),
            }
        )

    results.sort(
        key=lambda x: (int(x["doc_count"]), int(x["total_occurrences"])), reverse=True
    )
    return results[:top_k]


def compute_distinctive_ngrams(
    target_texts: Sequence[str],
    background_texts: Sequence[str],
    *,
    n: int = 2,
    top_k: int = 25,
    min_target_freq: int = 2,
    stop_words: frozenset[str] = STOP_WORDS,
) -> list[dict[str, object]]:
    """Compute distinctiveness-ranked n-grams comparing target cluster against background corpus."""
    target_counts: collections.Counter[str] = collections.Counter()
    target_doc_counts: collections.Counter[str] = collections.Counter()

    for text in target_texts:
        grams = extract_ngrams(text, n=n, stop_words=stop_words)
        target_counts.update(grams)
        target_doc_counts.update(set(grams))

    bg_counts: collections.Counter[str] = collections.Counter()
    bg_doc_counts: collections.Counter[str] = collections.Counter()

    for text in background_texts:
        grams = extract_ngrams(text, n=n, stop_words=stop_words)
        bg_counts.update(grams)
        bg_doc_counts.update(set(grams))

    num_target = len(target_texts) or 1
    num_bg = len(background_texts) or 1

    results: list[dict[str, object]] = []
    for term, t_doc_cnt in target_doc_counts.items():
        if t_doc_cnt < min_target_freq:
            continue
        t_freq = t_doc_cnt / num_target
        bg_doc_cnt = bg_doc_counts.get(term, 0)
        bg_freq = bg_doc_cnt / num_bg

        # Smoothed log odds / distinctiveness score
        score = (t_freq + 0.01) / (bg_freq + 0.01)
        specificity = t_doc_cnt / (t_doc_cnt + bg_doc_cnt)

        results.append(
            {
                "term": term,
                "target_docs": t_doc_cnt,
                "target_rate": round(t_freq, 4),
                "bg_docs": bg_doc_cnt,
                "bg_rate": round(bg_freq, 4),
                "score": round(score, 2),
                "specificity": round(specificity, 4),
            }
        )

    results.sort(key=lambda x: (float(x["score"]), int(x["target_docs"])), reverse=True)
    return results[:top_k]


def cluster_unclassified_tables(
    unclassified_records: Sequence[dict[str, Any]],
    *,
    min_cluster_size: int = 3,
    top_k: int = 25,
) -> list[dict[str, object]]:
    """Cluster unclassified tables by recurring row-stub & heading n-grams, calculating geometric profiles."""
    signature_to_slots: dict[str, set[int]] = collections.defaultdict(set)

    for slot, rec in enumerate(unclassified_records):
        row_text = str(rec.get("row_labels_text", ""))
        heading_text = str(rec.get("heading", ""))
        grams = (
            set(extract_ngrams(row_text, n=3))
            | set(extract_ngrams(row_text, n=2))
            | set(extract_ngrams(heading_text, n=2))
        )
        for g in grams:
            if len(g) > 4:
                signature_to_slots[g].add(slot)

    clusters: list[dict[str, object]] = []
    seen_slots: set[int] = set()

    for gram, slots in sorted(
        signature_to_slots.items(), key=lambda x: len(x[1]), reverse=True
    ):
        if len(slots) < min_cluster_size:
            continue
        new_slots = slots - seen_slots
        if len(new_slots) < min_cluster_size:
            continue

        cluster_recs = [unclassified_records[s] for s in new_slots]
        sample_headings = list(
            {str(r.get("heading", "")) for r in cluster_recs if r.get("heading")}
        )[:4]

        cols = [int(r["healed_cols"]) for r in cluster_recs if "healed_cols" in r]
        rows = [int(r["healed_rows"]) for r in cluster_recs if "healed_rows" in r]
        densities = [
            float(r["numeric_density"]) for r in cluster_recs if "numeric_density" in r
        ]

        avg_cols = round(statistics.mean(cols), 1) if cols else 0.0
        avg_rows = round(statistics.mean(rows), 1) if rows else 0.0
        avg_density = round(statistics.mean(densities), 3) if densities else 0.0

        clusters.append(
            {
                "signature": gram,
                "table_count": len(new_slots),
                "sample_headings": sample_headings,
                "sample_doc_paths": [
                    str(r.get("document_path", "")) for r in cluster_recs[:3]
                ],
                "avg_cols": avg_cols,
                "avg_rows": avg_rows,
                "avg_numeric_density": avg_density,
            }
        )
        seen_slots.update(new_slots)
        if len(clusters) >= top_k:
            break

    return clusters


__all__ = [
    "census_vocabulary",
    "cluster_unclassified_tables",
    "compute_distinctive_ngrams",
    "extract_all_ngrams",
    "extract_ngrams",
]
