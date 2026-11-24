"""Review summary roll-up and scorecard metrics for ownership cases."""

from __future__ import annotations

from collections import Counter
from typing import Any

from edgar_sec.engine.forms.ownership.analysis.fields import (
    DOCUMENT_FIELDS,
    FIELD_PATHS,
    FIELD_VALUE_TAGS,
    FIELD_WORD_LIMITS,
)
from edgar_sec.engine.forms.ownership.analysis.text import (
    extract_word_ngrams,
    mask_normalized_pattern,
)


def summarize_ownership_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate ownership case analyses into a run summary."""
    total_elements: Counter[str] = Counter()
    all_anomalies: list[dict[str, Any]] = []
    all_review_signals: list[dict[str, Any]] = []
    all_unparsed: list[dict[str, Any]] = []
    field_counts: Counter[str] = Counter()
    observation_counts: dict[str, Counter[str]] = {
        field: Counter() for field in FIELD_PATHS
    }
    field_case_counts: Counter[str] = Counter()

    for rep in case_reports:
        for tag, count in rep.get("element_counts", {}).items():
            total_elements[tag] += count
        for field, present in rep.get("core_fields", {}).items():
            if present:
                field_counts[field] += 1
        for field, observation in rep.get("field_observations", {}).items():
            observation_counts[field].update(observation)
            if observation.get("populated_occurrences", 0):
                field_case_counts[field] += 1
        all_anomalies.extend(rep.get("anomalies", []))
        all_review_signals.extend(rep.get("review_signals", []))
        all_unparsed.extend(rep.get("unparsed_sections", []))

    case_count = max(1, len(case_reports))
    field_completeness = {
        field: f"{field_counts[field]}/{case_count} ({field_counts[field] * 100 // case_count}%)"
        for field in (
            "periodOfReport",
            "issuerName",
            "issuerTradingSymbol",
            "rptOwnerName",
            "signatureName",
            "signatureDate",
        )
    }
    field_scorecard = {
        field: {
            "scope": "document" if field in DOCUMENT_FIELDS else "repeated_record",
            "cases_with_value": field_case_counts[field],
            "cases_without_value": len(case_reports) - field_case_counts[field],
            "case_missing_percent": round(
                (len(case_reports) - field_case_counts[field]) * 100 / case_count, 2
            ),
            "occurrences": observation_counts[field]["occurrences"],
            "populated_occurrences": observation_counts[field]["populated_occurrences"],
            "blank_occurrences": observation_counts[field]["blank_occurrences"],
        }
        for field in FIELD_PATHS
    }

    substantive_unparsed = [
        item for item in all_unparsed if not item.get("is_boilerplate")
    ]
    boilerplate_unparsed_count = len(all_unparsed) - len(substantive_unparsed)

    # Take representative samples prioritizing substantive unparsed sections
    seen_snippets: set[str] = set()
    unparsed_samples: list[dict[str, Any]] = []
    target_pool = substantive_unparsed if substantive_unparsed else all_unparsed
    for item in target_pool:
        snip = item["snippet"]
        if snip not in seen_snippets:
            seen_snippets.add(snip)
            unparsed_samples.append(item)
            if len(unparsed_samples) >= 10:
                break

    review_signal_samples = sorted(
        all_review_signals, key=lambda item: (item["accession"], item["value"])
    )[:20]

    # Outlier and uncommonness analysis across corpus
    missing_signatures = [
        rep["accession"]
        for rep in case_reports
        if not rep.get("core_fields", {}).get("signatureName")
    ]
    missing_periods = [
        rep["accession"]
        for rep in case_reports
        if not rep.get("core_fields", {}).get("periodOfReport")
    ]
    missing_owners = [
        rep["accession"]
        for rep in case_reports
        if not rep.get("core_fields", {}).get("rptOwnerName")
    ]

    word_count_outliers: list[dict[str, Any]] = []
    field_pattern_counts: dict[str, Counter[str]] = {
        f: Counter()
        for f in (
            "securityTitle",
            "underlyingSecurityTitle",
            "signatureName",
            "officerTitle",
        )
    }
    field_pattern_samples: dict[str, dict[str, str]] = {
        f: {}
        for f in (
            "securityTitle",
            "underlyingSecurityTitle",
            "signatureName",
            "officerTitle",
        )
    }
    field_ngram_counts: dict[str, Counter[str]] = {
        f: Counter()
        for f in (
            "securityTitle",
            "underlyingSecurityTitle",
            "signatureName",
            "officerTitle",
        )
    }
    value_counts: dict[str, Counter[str]] = {
        field: Counter() for field in FIELD_VALUE_TAGS
    }
    value_case_counts: dict[str, dict[str, set[str]]] = {
        field: {} for field in FIELD_VALUE_TAGS
    }

    for rep in case_reports:
        acc = rep.get("accession", "")
        for fld, vals in rep.get("field_values", {}).items():
            limit = FIELD_WORD_LIMITS.get(fld, 10)
            for v in vals:
                w_list = v.split()
                if len(w_list) > limit:
                    word_count_outliers.append(
                        {
                            "accession": acc,
                            "field": fld,
                            "word_count": len(w_list),
                            "value": v[:120],
                        }
                    )
                if fld in field_pattern_counts:
                    pat = mask_normalized_pattern(v)
                    field_pattern_counts[fld][pat] += 1
                    if pat not in field_pattern_samples[fld]:
                        field_pattern_samples[fld][pat] = acc
                    for ng in extract_word_ngrams(v, n=2):
                        field_ngram_counts[fld][ng] += 1
                if fld in value_counts:
                    value_counts[fld][v] += 1
                    value_case_counts[fld].setdefault(v, set()).add(acc)

    value_frequencies = {}
    for field, counts in value_counts.items():
        if not counts:
            continue
        top_values = [
            {
                "value": value,
                "count": count,
                "case_count": len(value_case_counts[field][value]),
                "sample_accession": min(value_case_counts[field][value]),
            }
            for value, count in counts.most_common(20)
        ]
        rare_values = [
            {
                "value": value,
                "count": count,
                "case_count": len(value_case_counts[field][value]),
                "sample_accession": min(value_case_counts[field][value]),
            }
            for value, count in sorted(
                counts.items(), key=lambda item: (item[1], item[0])
            )
            if count <= 2
        ][:20]
        value_frequencies[field] = {
            "occurrences": sum(counts.values()),
            "distinct_values": len(counts),
            "top_values": top_values,
            "rare_values": rare_values,
        }

    common_patterns_by_field: dict[str, list[dict[str, Any]]] = {}
    uncommon_patterns_by_field: dict[str, list[dict[str, Any]]] = {}
    rare_ngrams_by_field: dict[str, list[dict[str, Any]]] = {}

    for fld, pat_counter in field_pattern_counts.items():
        if not pat_counter:
            continue
        common_patterns_by_field[fld] = [
            {"pattern": p, "count": c} for p, c in pat_counter.most_common(5)
        ]
        uncommon_candidates = [
            {
                "pattern": p,
                "count": c,
                "sample_accession": field_pattern_samples[fld][p],
            }
            for p, c in sorted(pat_counter.items(), key=lambda kv: (kv[1], kv[0]))
            if c <= 2 and (case_count < 10 or c < case_count * 0.05)
        ]
        if uncommon_candidates:
            uncommon_patterns_by_field[fld] = uncommon_candidates[:5]

    for fld, ng_counter in field_ngram_counts.items():
        if not ng_counter:
            continue
        rare_candidates = [
            {"ngram": ng, "count": c}
            for ng, c in sorted(ng_counter.items(), key=lambda kv: (kv[1], kv[0]))
            if c <= 2 and (case_count < 10 or c < case_count * 0.05)
        ]
        if rare_candidates:
            rare_ngrams_by_field[fld] = rare_candidates[:5]

    return {
        "family": "4",
        "case_count": len(case_reports),
        "element_counts": dict(sorted(total_elements.items(), key=lambda kv: -kv[1])),
        "anomaly_count": len(all_anomalies),
        "anomalies": all_anomalies,
        "review_signal_count": len(all_review_signals),
        "review_signals": all_review_signals,
        "review_signal_samples": review_signal_samples,
        "unparsed_section_count": len(all_unparsed),
        "boilerplate_unparsed_count": boilerplate_unparsed_count,
        "substantive_unparsed_count": len(substantive_unparsed),
        "unparsed_samples": unparsed_samples,
        "field_completeness": field_completeness,
        "field_scorecard": field_scorecard,
        "value_frequencies": value_frequencies,
        "outliers": {
            "missing_fields": {
                "missing_signatures": {
                    "count": len(missing_signatures),
                    "sample_accessions": missing_signatures[:5],
                },
                "missing_periods": {
                    "count": len(missing_periods),
                    "sample_accessions": missing_periods[:5],
                },
                "missing_owners": {
                    "count": len(missing_owners),
                    "sample_accessions": missing_owners[:5],
                },
            },
            "word_count_outliers": word_count_outliers[:10],
            "common_patterns": common_patterns_by_field,
            "uncommon_patterns": uncommon_patterns_by_field,
            "rare_ngrams": rare_ngrams_by_field,
        },
    }


summarize_cases = summarize_ownership_cases
