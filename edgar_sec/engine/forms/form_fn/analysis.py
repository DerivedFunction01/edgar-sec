"""Form F-N review analysis: printed-form field extraction, scorecard."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from edgar_sec.domain.forms.families.form_fn.taxonomy import FORM_FN_LETTERED_ITEMS
from edgar_sec.engine.forms.analysis import (
    analyze_form_case,
    anomaly_record,
    locate_text_artifact,
    reinfer_unmasked_checkmarks,
    summarize_form_cases,
)
from edgar_sec.engine.forms.common.entities import extract_registration_number
from edgar_sec.engine.tables.protection.tags import find_table_spans

_KIND_KEYS: tuple[str, ...] = ("original_filing", "amended_filing")

_FILER_RE = re.compile(r"name of issuer or person filing[^:]*:\s*(.+)$", re.IGNORECASE)
_JURISDICTION_RE = re.compile(
    r"incorporated or organized under the laws of\s+(.+?)\s+and (?:each )?has its",
    re.IGNORECASE,
)
_BANK_ACT_RE = re.compile(r"under the bank act \(([^)]+)\)", re.IGNORECASE)
_AGENT_RE = re.compile(
    r"(?:designates and appoints|has designated and appointed)\s+(.+?)\s*\(",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"(?:333|33)-\d{3,}(?:-\d{2})?")

# Filed instances print items D and E as flowing sentences rather than
# under their captions; each letter accepts its sentence lead as well.
_LETTER_EVIDENCE: dict[str, tuple[str, ...]] = {
    letter: (title,) for letter, title in FORM_FN_LETTERED_ITEMS
}
_LETTER_EVIDENCE["D"] = (
    "filer jurisdiction and principal place of business",
    "incorporated or organized under the laws of",
    "schedule i bank under the bank act",
)
_LETTER_EVIDENCE["E"] = (
    "designation and appointment of agent for service of process",
    "designates and appoints",
)
_LETTER_EVIDENCE["F"] = (
    "successor agent stipulation and undertaking",
    "stipulates and agrees to appoint a successor agent",
)
_LETTER_EVIDENCE["G"] = (
    "undertaking to respond to commission staff inquiries",
    "undertakes to make available, in person or by telephone",
)


def _label_value(lines: list[str], label: str) -> str | None:
    """The value after a printed label, on its line or the next one.

    A parenthetical qualifier on the label ("File Number (if known)")
    precedes the value either way.
    """
    bare = label.rstrip(":").lower()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.lower().startswith(bare):
            continue
        rest = stripped[len(bare) :].strip()
        if rest.startswith("("):
            close = rest.find(")")
            if close >= 0:
                rest = rest[close + 1 :].strip()
        rest = rest.lstrip(":").strip()
        if rest:
            return rest
        for follow in lines[idx + 1 : idx + 3]:
            if follow.strip():
                return follow.strip()
        return None
    return None


def _form_fields(text: str, lines: list[str]) -> dict[str, Any]:
    filer = None
    for line in lines[:60]:
        match = _FILER_RE.search(line.strip())
        if match:
            filer = match.group(1).strip()
            break
    if not filer:
        filer = _label_value(lines, "name of registrant:")
    collapsed = " ".join(text.split())
    jurisdiction_match = _JURISDICTION_RE.search(collapsed)
    if not jurisdiction_match:
        jurisdiction_match = _BANK_ACT_RE.search(collapsed)
    agent_match = _AGENT_RE.search(collapsed)
    normalized = " ".join(text.lower().split())
    file_value = _label_value(lines, "file number")
    number_match = _NUMBER_RE.search(file_value) if file_value else None
    return {
        "filer_name": filer,
        "conjunction_registrant": _label_value(lines, "name of registrant:"),
        "conjunction_form_type": _label_value(lines, "form type:"),
        "conjunction_file_number": (
            number_match.group(0) if number_match else extract_registration_number(text)
        ),
        "conjunction_filed_by": _label_value(lines, "filed by:"),
        "conjunction_date_filed": _label_value(lines, "date filed"),
        "jurisdiction": (
            jurisdiction_match.group(1).strip() if jurisdiction_match else None
        ),
        "agent_name": agent_match.group(1).strip() if agent_match else None,
        "lettered_items_present": [
            letter
            for letter, phrases in _LETTER_EVIDENCE.items()
            if any(phrase in normalized for phrase in phrases)
        ],
    }


def analyze_form_fn_review_case(
    case_dir: Path, record: dict[str, Any]
) -> dict[str, Any] | None:
    """Analyze a single F-N review case producing field diagnostics."""
    rep = analyze_form_case(case_dir, record, form="F-N", family="F-N")
    if rep is None:
        return None
    text_path = locate_text_artifact(case_dir)
    text = (
        text_path.read_text(encoding="utf-8", errors="ignore")
        if text_path is not None
        else ""
    )
    lines = text.splitlines()
    if find_table_spans(text):
        reinfer_unmasked_checkmarks(text, rep, family="F-N")
    fields = _form_fields(text, lines)
    checked = set(rep["checkmarks"]["checked_keys"])
    fields["filing_kind"] = sorted(checked.intersection(_KIND_KEYS))
    rep["form_fn"] = fields

    if not fields["filer_name"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_filer_name",
                "no filer name matched at item A or the item C registrant line",
            )
        )
    if not fields["agent_name"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_agent_name",
                "no appointed agent matched at the item E designation",
            )
        )
    if not fields["filing_kind"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_filing_kind",
                "no original/amended filing box resolved as checked",
            )
        )
    return rep


def summarize_form_fn_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate individual F-N case analyses into an overall summary."""
    summary = summarize_form_cases(case_reports, family="F-N")
    total = summary.get("case_count", 0)
    if not total:
        return summary
    scorecard: dict[str, Any] = {
        "case_count": 0,
        "filer_name_count": 0,
        "agent_name_count": 0,
        "jurisdiction_count": 0,
        "conjunction_file_number_count": 0,
        "conjunction_form_type_count": 0,
        "filing_kind_counts": {},
        "lettered_item_counts": {},
    }
    for rep in case_reports:
        fields = rep.get("form_fn", {})
        scorecard["case_count"] += 1
        scorecard["filer_name_count"] += bool(fields.get("filer_name"))
        scorecard["agent_name_count"] += bool(fields.get("agent_name"))
        scorecard["jurisdiction_count"] += bool(fields.get("jurisdiction"))
        scorecard["conjunction_file_number_count"] += bool(
            fields.get("conjunction_file_number")
        )
        scorecard["conjunction_form_type_count"] += bool(
            fields.get("conjunction_form_type")
        )
        for key in fields.get("filing_kind", []):
            counts = scorecard["filing_kind_counts"]
            counts[key] = counts.get(key, 0) + 1
        for letter in fields.get("lettered_items_present", []):
            counts = scorecard["lettered_item_counts"]
            counts[letter] = counts.get(letter, 0) + 1
    summary["form_fn_scorecard"] = scorecard
    return summary


analyze_case = analyze_form_fn_review_case
summarize_cases = summarize_form_fn_cases

__all__ = [
    "analyze_case",
    "analyze_form_fn_review_case",
    "summarize_cases",
    "summarize_form_fn_cases",
]
