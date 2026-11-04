"""MJDS review analysis and scorecard aggregation (F-7/F-8/F-9/F-10/F-80)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.forms.families.form_mjds.taxonomy import (
    MJDS_PROSPECTUS_HEADINGS,
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
    "rule_467a_upon_filing",
    "effectiveness_future_date",
    "rule_467b_designated_date",
    "rule_467b_receipt_clearance",
    "rule_467b_notification",
)

_ELECTION_FAMILIES = frozenset({"F-9", "F-10"})

_HEADING_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (
        heading,
        re.compile(
            r"^\s*" + re.escape(heading) + r"\s*(?:\.{2,}.*|\d{1,3})?\s*$",
            re.IGNORECASE,
        ),
    )
    for heading in MJDS_PROSPECTUS_HEADINGS
)


def _prospectus_hits(body_lines: list[str]) -> list[str]:
    remaining = dict(_HEADING_PATTERNS)
    hits: list[str] = []
    for line in body_lines:
        if not remaining:
            break
        if len(line) > 90:
            continue
        for heading, pattern in list(remaining.items()):
            if pattern.match(line):
                hits.append(heading)
                del remaining[heading]
    return hits


def analyze_form_mjds_review_case(
    case_dir: Path, record: dict[str, Any]
) -> dict[str, Any] | None:
    """Analyze a single MJDS review case producing cover-field diagnostics."""
    resolved_form = str(record.get("form") or record.get("family") or "F-10")
    family = resolve_alias(resolved_form) or resolved_form
    text_path = locate_text_artifact(case_dir)
    if text_path is None:
        return None
    try:
        text = text_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    rep = analyze_form_case(
        case_dir, record, form=resolved_form, family=family, text=text
    )
    if rep is None:
        return None
    lines = text.splitlines()
    if find_table_spans(text):
        reinfer_unmasked_checkmarks(text, rep, family=family)
    start = rep["boundary"]["start_line"] or 0
    end = rep["boundary"]["end_line"] or 0
    cover_text = "\n".join(lines[start:end]) if end > start else ""

    fields = facing_sheet_fields(cover_text, lines, resolved_form)
    checked = set(rep["checkmarks"]["checked_keys"])
    election = sorted(checked.intersection(_ELECTION_KEYS))
    fields["effectiveness_election"] = election
    if family in _ELECTION_FAMILIES:
        fields["prospectus_headings"] = _prospectus_hits(lines)
    rep["form_mjds"] = fields

    if not fields["registration_number"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_registration_number",
                "no registration number matched in the cover header",
            )
        )
    if not fields["registrant_name"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_registrant_name",
                "no registrant name resolved from the cover header",
            )
        )
    if family in _ELECTION_FAMILIES and not election:
        rep["anomalies"].append(
            anomaly_record(
                "missing_effectiveness_election",
                "no Rule 467 election box resolved as checked",
            )
        )
    return rep


def summarize_form_mjds_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate individual MJDS case analyses into an overall summary."""
    summary = summarize_form_cases(case_reports, family="MJDS")
    total = summary.get("case_count", 0)
    if not total:
        return summary

    def fields_of(rep: dict[str, Any]) -> dict[str, Any]:
        return rep.get("form_mjds", {})

    per_family: dict[str, dict[str, Any]] = {}
    for rep in case_reports:
        bucket = per_family.setdefault(
            rep["family"],
            {
                "case_count": 0,
                "registrant_name_count": 0,
                "registration_number_count": 0,
                "fee_table_count": 0,
                "election_decision_count": 0,
                "document_kind_counts": {},
                "prospectus_heading_counts": {},
            },
        )
        fields = fields_of(rep)
        bucket["case_count"] += 1
        bucket["registrant_name_count"] += bool(fields.get("registrant_name"))
        bucket["registration_number_count"] += bool(fields.get("registration_number"))
        bucket["fee_table_count"] += bool(fields.get("fee_table_present"))
        bucket["election_decision_count"] += bool(fields.get("effectiveness_election"))
        kind = fields.get("document_kind")
        if kind:
            kinds = bucket["document_kind_counts"]
            kinds[kind] = kinds.get(kind, 0) + 1
        for heading in fields.get("prospectus_headings", []):
            counts = bucket["prospectus_heading_counts"]
            counts[heading] = counts.get(heading, 0) + 1
    summary["form_mjds_scorecard"] = per_family
    return summary


analyze_case = analyze_form_mjds_review_case
summarize_cases = summarize_form_mjds_cases

__all__ = [
    "analyze_case",
    "analyze_form_mjds_review_case",
    "summarize_cases",
    "summarize_form_mjds_cases",
]
