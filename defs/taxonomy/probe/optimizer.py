"""Auto-classification engine, keyword density optimizer, and non-colliding spec synthesizer."""

from __future__ import annotations

import collections
from typing import TYPE_CHECKING, Any

from defs.taxonomy.probe.census import extract_ngrams

if TYPE_CHECKING:
    from collections.abc import Sequence


def evaluate_keyword_density(
    target_records: Sequence[dict[str, Any]],
    background_records: Sequence[dict[str, Any]],
    candidate_phrases: list[str],
    *,
    min_k: int = 1,
    max_k: int = 4,
    zone: str = "row_labels",
) -> list[dict[str, object]]:
    """Evaluate keyword combination density and collision curves to find zero-FP thresholds."""
    zone_key = {
        "row_labels": "row_labels_text",
        "headers": "header_text",
        "full": "full_normalized_text",
    }.get(zone, "row_labels_text")

    target_texts = [str(r.get(zone_key, "")).lower() for r in target_records]
    bg_texts = [str(r.get(zone_key, "")).lower() for r in background_records]

    results: list[dict[str, object]] = []

    for k in range(min_k, min(max_k + 1, len(candidate_phrases) + 1)):
        # Overall threshold k: matches at least k of any candidate phrase
        t_hits = sum(
            1
            for text in target_texts
            if sum(1 for p in candidate_phrases if p in text) >= k
        )
        bg_hits = sum(
            1
            for text in bg_texts
            if sum(1 for p in candidate_phrases if p in text) >= k
        )

        precision = t_hits / max(1, t_hits + bg_hits)
        recall = t_hits / max(1, len(target_texts))

        results.append(
            {
                "k_threshold": k,
                "target_captured": t_hits,
                "target_recall": round(recall, 4),
                "background_fps": bg_hits,
                "precision": round(precision, 4),
                "is_zero_fp": bool(bg_hits == 0),
            }
        )

    return results


def synthesize_candidate_family(
    cluster_records: Sequence[dict[str, Any]],
    background_records: Sequence[dict[str, Any]],
    *,
    cluster_name: str,
    top_candidates: int = 6,
) -> dict[str, object]:
    """Synthesize an optimal, non-colliding candidate TableFamilySpec JSON from a table cluster."""
    # Mine top distinctive bigrams & trigrams in row stubs and headers
    row_target = [str(r.get("row_labels_text", "")).lower() for r in cluster_records]
    row_bg = [str(r.get("row_labels_text", "")).lower() for r in background_records]

    # Extract high-frequency candidate phrases in cluster
    target_row_counts: collections.Counter[str] = collections.Counter()
    for text in row_target:
        grams = extract_ngrams(text, n=2) + extract_ngrams(text, n=3)
        target_row_counts.update(set(grams))

    # Calculate background collision counts for each candidate
    candidate_scores: list[tuple[str, int, int, float]] = []
    for phrase, t_cnt in target_row_counts.most_common(50):
        if len(phrase) < 4:
            continue
        bg_cnt = sum(1 for t in row_bg if phrase in t)
        precision = t_cnt / (t_cnt + bg_cnt) if (t_cnt + bg_cnt) > 0 else 0.0
        candidate_scores.append((phrase, t_cnt, bg_cnt, precision))

    candidate_scores.sort(key=lambda x: (x[3], x[1]), reverse=True)

    required_phrases = [p for p, t_cnt, bg_cnt, prec in candidate_scores[:3]]
    supporting_phrases = [
        p for p, t_cnt, bg_cnt, prec in candidate_scores[3:top_candidates]
    ]

    # Evaluate density curve
    density_curve = evaluate_keyword_density(
        cluster_records,
        background_records,
        required_phrases + supporting_phrases,
        min_k=1,
        max_k=3,
    )

    # Calculate geometric constraints
    cols = [int(r.get("healed_cols", 2)) for r in cluster_records]
    rows = [int(r.get("healed_rows", 2)) for r in cluster_records]
    densities = [float(r.get("numeric_density", 0.0)) for r in cluster_records]

    min_cols = max(2, min(cols)) if cols else 2
    min_rows = max(2, min(rows)) if rows else 2
    min_num_density = round(min(densities), 2) if densities else 0.0

    return {
        "family_name": cluster_name,
        "required_phrases": required_phrases,
        "supporting_phrases": supporting_phrases,
        "exclusions": [],
        "min_cols": min_cols,
        "min_rows": min_rows,
        "min_numeric_density": min_num_density,
        "density_curve": density_curve,
        "tables_captured": len(cluster_records),
    }


def detect_union_candidates(
    records: Sequence[dict[str, Any]],
) -> list[dict[str, object]]:
    """Detect multi-part table schedule candidates (adjacent tables under identical heading/item)."""
    by_doc: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for rec in records:
        doc_id = str(rec.get("doc_id", ""))
        by_doc[doc_id].append(rec)

    unions: list[dict[str, object]] = []

    for doc_id, doc_recs in by_doc.items():
        doc_recs.sort(key=lambda x: int(x.get("table_index", 0)))
        current_group: list[dict[str, Any]] = []

        for r in doc_recs:
            heading = str(r.get("heading", "")).strip()

            if not heading and not str(r.get("item_label", "")).strip():
                continue

            if current_group:
                prev = current_group[-1]
                prev_heading = str(prev.get("heading", "")).strip()
                prev_idx = int(prev.get("table_index", 0))
                cur_idx = int(r.get("table_index", 0))

                # If adjacent tables share the same specific footnote heading
                if (
                    len(heading) > 10
                    and heading == prev_heading
                    and cur_idx == prev_idx + 1
                ):
                    current_group.append(r)
                    continue
                else:
                    if len(current_group) >= 2:
                        unions.append(
                            {
                                "doc_id": doc_id,
                                "heading": prev_heading,
                                "table_count": len(current_group),
                                "table_indices": [
                                    int(x.get("table_index", 0)) for x in current_group
                                ],
                            }
                        )
                    current_group = [r]
            else:
                current_group = [r]

        if len(current_group) >= 2:
            unions.append(
                {
                    "doc_id": doc_id,
                    "heading": str(current_group[0].get("heading", "")),
                    "table_count": len(current_group),
                    "table_indices": [
                        int(x.get("table_index", 0)) for x in current_group
                    ],
                }
            )

    return unions


__all__ = [
    "detect_union_candidates",
    "evaluate_keyword_density",
    "synthesize_candidate_family",
]
