"""Form 40-F review analysis and scorecard aggregation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from edgar_sec.domain.forms.families.form_40f.taxonomy import (
    FORM_40F_FURNISHED_KINDS,
)
from edgar_sec.engine.forms.analysis import (
    analyze_form_case,
    anomaly_record,
    locate_text_artifact,
    reinfer_unmasked_checkmarks,
    summarize_form_cases,
)
from edgar_sec.engine.forms.common.facing_sheet import facing_sheet_fields
from edgar_sec.engine.tables.protection.tags import find_table_spans

_ELECTION_KEYS: tuple[str, ...] = (
    "section_12_registration",
    "section_13a_15d_annual_report",
)

_FURNISHED_MARK_KEYS: tuple[str, ...] = (
    "furnished_aif",
    "furnished_audited_financial_statements",
    "rule_12g3_2b_furnishing",
)


_TITLE_ELECTIONS: tuple[tuple[str, str], ...] = (
    (
        "annual report pursuant to section 13(a) or 15(d)",
        "section_13a_15d_annual_report",
    ),
    ("annual report pursuant to section 13 or 15(d)", "section_13a_15d_annual_report"),
    (
        "annual report pursuant to section 13(1) or 15(d)",
        "section_13a_15d_annual_report",
    ),
    ("annual report pursuant to section 13(a)", "section_13a_15d_annual_report"),
    ("registration statement pursuant to section 12", "section_12_registration"),
)


def _title_election(lines: list[str]) -> str | None:
    """The election an era cover declares as its printed subtitle line."""
    found = {
        key
        for line in lines[:20]
        for phrase, key in _TITLE_ELECTIONS
        if line.strip().lower().startswith(phrase)
    }
    return found.pop() if len(found) == 1 else None


def _furnished_segments(body_text: str, lines: list[str]) -> list[str]:
    lowered = body_text.lower()
    heading_lines = {line.strip().lower() for line in lines if len(line) <= 80}
    return [
        kind
        for kind, phrases in FORM_40F_FURNISHED_KINDS.items()
        if any(phrase in lowered or phrase in heading_lines for phrase in phrases)
    ]


def analyze_form_40f_review_case(
    case_dir: Path, record: dict[str, Any]
) -> dict[str, Any] | None:
    """Analyze a single 40-F review case producing cover-field diagnostics."""
    resolved_form = str(record.get("form") or record.get("family") or "40-F")
    text_path = locate_text_artifact(case_dir)
    if text_path is None:
        return None
    try:
        text = text_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    rep = analyze_form_case(
        case_dir, record, form=resolved_form, family="40-F", text=text
    )
    if rep is None:
        return None
    lines = text.splitlines()
    if find_table_spans(text):
        reinfer_unmasked_checkmarks(text, rep, family="40-F", case_dir=case_dir)
    start = rep["boundary"]["start_line"] or 0
    end = rep["boundary"]["end_line"] or 0
    cover_text = "\n".join(lines[start:end]) if end > start else ""

    fields = facing_sheet_fields(cover_text, lines, resolved_form)
    checked = set(rep["checkmarks"]["checked_keys"])
    candidates = rep["checkmarks"]["candidate_states"]
    fields["election"] = sorted(checked.intersection(_ELECTION_KEYS))
    fields["election_source"] = "checkmark" if fields["election"] else None
    if not fields["election"]:
        title_key = _title_election(lines)
        if title_key:
            fields["election"] = [title_key]
            fields["election_source"] = "title"
    fields["furnished_marks"] = sorted(
        key for key in _FURNISHED_MARK_KEYS if candidates.get(key) == "checked"
    )
    fields["furnished_segments"] = _furnished_segments("\n".join(lines[end:]), lines)
    rep["form_40f"] = fields

    if not fields["election"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_election_decision",
                "no Section 12 / Section 13(a)-15(d) election box resolved",
            )
        )
    if not fields["registrant_name"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_registrant_name",
                "no registrant name resolved from the cover header",
            )
        )
    return rep


def summarize_form_40f_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate individual 40-F case analyses into an overall summary."""
    summary = summarize_form_cases(case_reports, family="40-F")
    total = summary.get("case_count", 0)
    if not total:
        return summary

    def fields_of(rep: dict[str, Any]) -> dict[str, Any]:
        return rep.get("form_40f", {})

    election_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    mark_counts: dict[str, int] = {}
    segment_counts: dict[str, int] = {}
    for rep in case_reports:
        fields = fields_of(rep)
        for key in fields.get("election", []):
            election_counts[key] = election_counts.get(key, 0) + 1
        source = fields.get("election_source")
        if source:
            source_counts[source] = source_counts.get(source, 0) + 1
        for key in fields.get("furnished_marks", []):
            mark_counts[key] = mark_counts.get(key, 0) + 1
        for kind in fields.get("furnished_segments", []):
            segment_counts[kind] = segment_counts.get(kind, 0) + 1

    summary["form_40f_scorecard"] = {
        "registrant_name_count": sum(
            1 for r in case_reports if fields_of(r).get("registrant_name")
        ),
        "registration_number_count": sum(
            1 for r in case_reports if fields_of(r).get("registration_number")
        ),
        "election_decision_count": sum(
            1 for r in case_reports if fields_of(r).get("election")
        ),
        "election_counts": election_counts,
        "election_source_counts": source_counts,
        "furnished_mark_counts": mark_counts,
        "furnished_segment_counts": segment_counts,
    }
    return summary


analyze_case = analyze_form_40f_review_case
summarize_cases = summarize_form_40f_cases

__all__ = [
    "analyze_case",
    "analyze_form_40f_review_case",
    "summarize_cases",
    "summarize_form_40f_cases",
]
