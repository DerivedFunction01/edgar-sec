"""Review summary roll-up and scorecard metrics for beneficial ownership cases."""

from __future__ import annotations

from collections import Counter
from typing import Any

from edgar_sec.engine.forms.beneficial_ownership.vocabulary import (
    CATEGORICAL_FIELDS,
    FIELD_TAGS,
)


def summarize_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate case review outcomes into cross-filing metrics and scorecard."""
    case_count = len(case_reports)
    observations: dict[str, Counter[str]] = {field: Counter() for field in FIELD_TAGS}
    anomalies: list[dict[str, Any]] = []
    anomaly_counts: Counter[str] = Counter()
    anomaly_case_accessions: dict[str, set[str]] = {}
    anomaly_field_counts: Counter[str] = Counter()
    anomaly_field_accessions: dict[str, set[str]] = {}
    review_signals: list[dict[str, Any]] = []
    review_signal_counts: Counter[str] = Counter()
    review_signal_accessions: dict[str, set[str]] = {}
    extraction_coverage: list[dict[str, Any]] = []
    unparsed_sections: list[dict[str, Any]] = []
    boilerplate_unparsed_count = 0
    value_counts: dict[str, Counter[str]] = {
        name: Counter() for name in CATEGORICAL_FIELDS
    }
    value_cases: dict[str, dict[str, set[str]]] = {
        name: {} for name in CATEGORICAL_FIELDS
    }

    for report in case_reports:
        accession = str(report.get("accession", ""))
        for field, fields in report.get("field_observations", {}).items():
            for key in ("occurrences", "populated_occurrences", "blank_occurrences"):
                observations.setdefault(field, Counter())[key] += fields.get(key, 0)
            if fields.get("populated_occurrences", 0):
                observations[field]["cases_with_value"] += 1
        for anomaly in report.get("anomalies", []):
            kind = anomaly["kind"]
            anomaly_counts[kind] += 1
            anomaly_case_accessions.setdefault(kind, set()).add(accession)
            if field := anomaly.get("field"):
                field_key = f"{kind}:{field}"
                anomaly_field_counts[field_key] += 1
                anomaly_field_accessions.setdefault(field_key, set()).add(accession)
            anomalies.append(anomaly)
        for signal in report.get("review_signals", []):
            kind = signal["kind"]
            review_signal_counts[kind] += 1
            review_signal_accessions.setdefault(kind, set()).add(accession)
            review_signals.append(signal)
        if coverage := report.get("extraction_coverage"):
            extraction_coverage.append(coverage)
        case_unparsed = report.get("unparsed_sections", [])
        unparsed_sections.extend(case_unparsed)
        boilerplate_unparsed_count += sum(
            bool(section.get("is_boilerplate")) for section in case_unparsed
        )
        for field, values in report.get("value_frequencies", {}).items():
            for value in values:
                value_counts.setdefault(field, Counter())[value] += 1
                value_cases.setdefault(field, {}).setdefault(value, set()).add(
                    accession
                )

    field_scorecard = {
        field: {
            **dict(counts),
            "cases_without_value": max(0, case_count - counts["cases_with_value"]),
            "case_missing_percent": round(
                max(0, case_count - counts["cases_with_value"])
                * 100
                / max(1, case_count),
                2,
            ),
        }
        for field, counts in sorted(observations.items())
    }
    value_summary = {
        field: {
            "distinct_values": len(counts),
            "top_values": [
                {
                    "value": value,
                    "count": count,
                    "case_count": len(value_cases[field][value]),
                    "sample_accession": min(value_cases[field][value]),
                }
                for value, count in counts.most_common(10)
            ],
        }
        for field, counts in sorted(value_counts.items())
    }
    substantive_unparsed = [
        section for section in unparsed_sections if not section.get("is_boilerplate")
    ]
    sample_pool = substantive_unparsed if substantive_unparsed else unparsed_sections
    unparsed_samples: list[dict[str, Any]] = []
    seen_snippets: set[str] = set()
    for section in sample_pool:
        snippet = section.get("snippet", "")
        if snippet not in seen_snippets:
            seen_snippets.add(snippet)
            unparsed_samples.append(section)
            if len(unparsed_samples) == 10:
                break

    families = sorted({str(report.get("family", "13D")) for report in case_reports})
    coverage_summary = {
        "case_count": len(extraction_coverage),
        "source_length": sum(
            int(report.get("source_length", 0)) for report in extraction_coverage
        ),
        "source_nonwhitespace_characters": sum(
            int(report.get("source_nonwhitespace_characters", 0))
            for report in extraction_coverage
        ),
        "mapped_nonwhitespace_characters": sum(
            int(report.get("mapped_nonwhitespace_characters", 0))
            for report in extraction_coverage
        ),
        "unparsed_nonwhitespace_characters": sum(
            int(report.get("unparsed_nonwhitespace_characters", 0))
            for report in extraction_coverage
        ),
        "uncovered_nonwhitespace_characters": sum(
            int(report.get("uncovered_nonwhitespace_characters", 0))
            for report in extraction_coverage
        ),
        "field_extraction_count": sum(
            int(report.get("field_extraction_count", 0))
            for report in extraction_coverage
        ),
    }
    coverage_summary["mapped_percent"] = round(
        coverage_summary["mapped_nonwhitespace_characters"]
        * 100
        / max(1, coverage_summary["source_nonwhitespace_characters"]),
        2,
    )
    coverage_summary["unparsed_percent"] = round(
        coverage_summary["unparsed_nonwhitespace_characters"]
        * 100
        / max(1, coverage_summary["source_nonwhitespace_characters"]),
        2,
    )
    return {
        "family": families[0] if len(families) == 1 else "mixed" if families else "13D",
        "case_count": case_count,
        "field_scorecard": field_scorecard,
        "anomalies": anomalies,
        "anomaly_count": len(anomalies),
        "anomaly_summary": {
            "kind_counts": dict(sorted(anomaly_counts.items())),
            "kind_case_counts": {
                kind: len(accessions)
                for kind, accessions in sorted(anomaly_case_accessions.items())
            },
            "field_counts": dict(sorted(anomaly_field_counts.items())),
            "field_case_counts": {
                field: len(accessions)
                for field, accessions in sorted(anomaly_field_accessions.items())
            },
            "sample_anomalies": anomalies[:10],
        },
        "review_signals": review_signals,
        "review_signal_count": len(review_signals),
        "review_signal_summary": {
            "kind_counts": dict(sorted(review_signal_counts.items())),
            "kind_case_counts": {
                kind: len(accessions)
                for kind, accessions in sorted(review_signal_accessions.items())
            },
        },
        "unparsed_section_count": len(unparsed_sections),
        "unparsed_character_count": sum(
            int(section.get("char_length", 0)) for section in unparsed_sections
        ),
        "boilerplate_unparsed_count": boilerplate_unparsed_count,
        "substantive_unparsed_count": len(substantive_unparsed),
        "unparsed_samples": unparsed_samples,
        "extraction_coverage": coverage_summary,
        "value_frequencies": value_summary,
    }
