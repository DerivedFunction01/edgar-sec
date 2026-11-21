"""Unit tests for beneficial ownership review summarizer."""

from edgar_sec.engine.forms.beneficial_ownership.analysis.summary import summarize_cases


def test_summary_counts_anomaly_occurrences_and_distinct_cases() -> None:
    reports = [
        {
            "accession": "0000000001-24-000001",
            "family": "13D",
            "field_observations": {
                "issuerName": {
                    "occurrences": 1,
                    "populated_occurrences": 1,
                    "blank_occurrences": 0,
                }
            },
            "anomalies": [
                {
                    "accession": "0000000001-24-000001",
                    "kind": "missing_required_schema_field",
                    "field": "securitiesClassTitle",
                },
                {
                    "accession": "0000000001-24-000001",
                    "kind": "missing_required_schema_field",
                    "field": "securitiesClassTitle",
                },
            ],
            "review_signals": [
                {
                    "accession": "0000000001-24-000001",
                    "kind": "short_cusip_value",
                    "field": "issuerCusip",
                }
            ],
            "unparsed_sections": [],
            "value_frequencies": {"citizenshipOrOrganization": ["DE"]},
            "extraction_coverage": {
                "source_length": 100,
                "source_nonwhitespace_characters": 80,
                "mapped_nonwhitespace_characters": 60,
                "unparsed_nonwhitespace_characters": 20,
                "uncovered_nonwhitespace_characters": 0,
                "field_extraction_count": 3,
            },
        },
        {
            "accession": "0000000002-24-000002",
            "family": "13D",
            "field_observations": {
                "issuerName": {
                    "occurrences": 1,
                    "populated_occurrences": 1,
                    "blank_occurrences": 0,
                }
            },
            "anomalies": [
                {
                    "accession": "0000000002-24-000002",
                    "kind": "missing_required_schema_field",
                    "field": "securitiesClassTitle",
                }
            ],
            "review_signals": [],
            "unparsed_sections": [],
            "value_frequencies": {"citizenshipOrOrganization": ["DE", "NY"]},
            "extraction_coverage": {
                "source_length": 100,
                "source_nonwhitespace_characters": 80,
                "mapped_nonwhitespace_characters": 70,
                "unparsed_nonwhitespace_characters": 10,
                "uncovered_nonwhitespace_characters": 0,
                "field_extraction_count": 4,
            },
        },
    ]

    summary = summarize_cases(reports)

    assert summary["case_count"] == 2
    assert summary["anomaly_count"] == 3
    assert (
        summary["anomaly_summary"]["kind_counts"]["missing_required_schema_field"] == 3
    )
    assert (
        summary["anomaly_summary"]["kind_case_counts"]["missing_required_schema_field"]
        == 2
    )
    assert (
        summary["anomaly_summary"]["field_counts"][
            "missing_required_schema_field:securitiesClassTitle"
        ]
        == 3
    )
    assert (
        summary["anomaly_summary"]["field_case_counts"][
            "missing_required_schema_field:securitiesClassTitle"
        ]
        == 2
    )
    assert summary["review_signal_count"] == 1
    assert summary["review_signal_summary"]["kind_counts"]["short_cusip_value"] == 1
    assert (
        summary["review_signal_summary"]["kind_case_counts"]["short_cusip_value"] == 1
    )
    assert summary["field_scorecard"]["issuerName"]["cases_with_value"] == 2
    assert summary["field_scorecard"]["issuerName"]["case_missing_percent"] == 0.0
    de_entry = next(
        item
        for item in summary["value_frequencies"]["citizenshipOrOrganization"][
            "top_values"
        ]
        if item["value"] == "DE"
    )
    assert de_entry["count"] == 2
    assert de_entry["case_count"] == 2


def test_summary_filters_statutory_unparsed_sections() -> None:
    reports = [
        {
            "accession": "0000000001-24-000001",
            "family": "13D",
            "field_observations": {},
            "anomalies": [],
            "review_signals": [],
            "unparsed_sections": [
                {
                    "accession": "0000000001-24-000001",
                    "role": "unparsed",
                    "snippet": "SCHEDULE 13D Page 1 of 5",
                    "char_length": 25,
                    "is_boilerplate": True,
                },
                {
                    "accession": "0000000001-24-000001",
                    "role": "unparsed",
                    "snippet": "Custom narrative section content",
                    "char_length": 32,
                    "is_boilerplate": False,
                },
            ],
            "value_frequencies": {},
            "extraction_coverage": {
                "source_length": 100,
                "source_nonwhitespace_characters": 80,
                "mapped_nonwhitespace_characters": 60,
                "unparsed_nonwhitespace_characters": 20,
                "uncovered_nonwhitespace_characters": 0,
                "field_extraction_count": 3,
            },
        }
    ]

    summary = summarize_cases(reports)

    assert summary["unparsed_section_count"] == 2
    assert summary["boilerplate_unparsed_count"] == 1
    assert summary["substantive_unparsed_count"] == 1
    assert len(summary["unparsed_samples"]) == 1
    assert (
        summary["unparsed_samples"][0]["snippet"] == "Custom narrative section content"
    )
