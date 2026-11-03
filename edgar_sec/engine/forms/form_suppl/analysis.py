"""SUPPL review analysis: the supplement caption parse and scorecard."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from edgar_sec.domain.forms.families.form_mjds.taxonomy import (
    MJDS_PROSPECTUS_HEADINGS,
)
from edgar_sec.domain.forms.families.form_suppl.taxonomy import (
    FORM_SUPPL_KINDS,
)
from edgar_sec.engine.forms.analysis import (
    analyze_form_case,
    anomaly_record,
    locate_text_artifact,
    summarize_form_cases,
)
from edgar_sec.engine.forms.common.entities import extract_registration_number
from edgar_sec.engine.forms.common.facing_sheet import facing_sheet_fields

_INSTRUCTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"general instructions? (?:ii|11)\s*\.\s*([kl])\.?\s*(?:of|to) "
        r"(?:form\s+)?f\s*-\s*(9|10)",
        re.IGNORECASE,
    ),
    re.compile(
        r"general instructions? (?:ii|il)([kl])\.? (?:of|to) "
        r"(?:form\s+)?f\s*-\s*(9|10)",
        re.IGNORECASE,
    ),
    re.compile(
        r"general instructions? (?:ii|11)\s*\.\s*([kl])\.?\s*(?:of|to) form-(9|10)",
        re.IGNORECASE,
    ),
)

_DATE_RE = re.compile(
    r"(?:base shelf prospectus dated\s+(?:as of\s+)?|prospectus dated\s+)"
    r"([A-Z][a-z]+ \d{1,2}, \d{4})",
    re.IGNORECASE,
)

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


def _heading_hits(lines: list[str]) -> list[str]:
    remaining = dict(_HEADING_PATTERNS)
    hits: list[str] = []
    for line in lines:
        if not remaining:
            break
        if len(line) > 90:
            continue
        for heading, pattern in list(remaining.items()):
            if pattern.match(line):
                hits.append(heading)
                del remaining[heading]
    return hits


def _supplement_kind(lines: list[str]) -> str | None:
    kinds = sorted(FORM_SUPPL_KINDS, key=len, reverse=True)
    for line in lines[:80]:
        lowered = " ".join(line.lower().split())
        if len(lowered) > 90:
            continue
        for kind in kinds:
            if kind in lowered:
                return kind
    for line in lines[:40]:
        lowered = " ".join(line.lower().split())
        for kind in kinds:
            if lowered.find(kind) in range(0, 60):
                return kind
    for line in lines[:15]:
        stripped = line.strip().lower()
        if stripped.startswith(("[supplement", "supplement")):
            return "supplement"
    return None


def _caption_fields(text: str, lines: list[str]) -> dict[str, Any]:
    normalized = " ".join(text.lower().split())
    match = next(
        (m for pattern in _INSTRUCTION_PATTERNS if (m := pattern.search(normalized))),
        None,
    )
    base_form = None
    instruction_reference = None
    if match:
        instruction_reference = match.group(0)
        base_form = f"F-{match.group(2)}"
    date_match = _DATE_RE.search(text)
    return {
        "base_form": base_form,
        "instruction_reference": instruction_reference,
        "file_number": extract_registration_number(text),
        "supplement_kind": _supplement_kind(lines),
        "base_prospectus_date": date_match.group(1) if date_match else None,
    }


def analyze_form_suppl_review_case(
    case_dir: Path, record: dict[str, Any]
) -> dict[str, Any] | None:
    """Analyze a single SUPPL review case producing caption diagnostics."""
    rep = analyze_form_case(case_dir, record, form="SUPPL", family="SUPPL")
    if rep is None:
        return None
    text_path = locate_text_artifact(case_dir)
    text = (
        text_path.read_text(encoding="utf-8", errors="ignore")
        if text_path is not None
        else ""
    )
    lines = text.splitlines()
    start = rep["boundary"]["start_line"] or 0
    end = rep["boundary"]["end_line"] or 0
    cover_text = "\n".join(lines[start:end]) if end > start else ""

    fields = facing_sheet_fields(cover_text, lines, "SUPPL")
    fields.update(_caption_fields(text, lines))
    if not fields["file_number"]:
        fields["file_number"] = fields["registration_number"]
    fields["prospectus_headings"] = _heading_hits(lines)
    rep["form_suppl"] = fields

    if not fields["base_form"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_base_form",
                "no general-instruction reference to a base form matched",
            )
        )
    if not fields["file_number"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_file_number",
                "no file number matched in the caption or cover",
            )
        )
    if not fields["supplement_kind"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_supplement_kind",
                "no supplement kind caption matched in the cover head",
            )
        )
    return rep


def summarize_form_suppl_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate individual SUPPL case analyses into an overall summary."""
    summary = summarize_form_cases(case_reports, family="SUPPL")
    total = summary.get("case_count", 0)
    if not total:
        return summary
    scorecard: dict[str, Any] = {
        "case_count": 0,
        "registrant_name_count": 0,
        "file_number_count": 0,
        "base_date_count": 0,
        "base_form_counts": {},
        "kind_counts": {},
        "prospectus_heading_counts": {},
    }
    for rep in case_reports:
        fields = rep.get("form_suppl", {})
        scorecard["case_count"] += 1
        scorecard["registrant_name_count"] += bool(fields.get("registrant_name"))
        scorecard["file_number_count"] += bool(fields.get("file_number"))
        scorecard["base_date_count"] += bool(fields.get("base_prospectus_date"))
        base = fields.get("base_form")
        if base:
            counts = scorecard["base_form_counts"]
            counts[base] = counts.get(base, 0) + 1
        kind = fields.get("supplement_kind")
        if kind:
            counts = scorecard["kind_counts"]
            counts[kind] = counts.get(kind, 0) + 1
        for heading in fields.get("prospectus_headings", []):
            counts = scorecard["prospectus_heading_counts"]
            counts[heading] = counts.get(heading, 0) + 1
    summary["form_suppl_scorecard"] = scorecard
    return summary


analyze_case = analyze_form_suppl_review_case
summarize_cases = summarize_form_suppl_cases

__all__ = [
    "analyze_case",
    "analyze_form_suppl_review_case",
    "summarize_cases",
    "summarize_form_suppl_cases",
]
