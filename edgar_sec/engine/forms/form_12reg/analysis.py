"""Section 12 cluster review analysis and scorecard aggregation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.forms.families.form_12reg.models import Form12RegKind
from edgar_sec.domain.forms.families.form_12reg.taxonomy import kind_of
from edgar_sec.engine.forms.analysis import (
    analyze_form_case,
    anomaly_record,
    locate_text_artifact,
    summarize_form_cases,
)
from edgar_sec.engine.forms.cover.registrant import (
    extract_commission_file_number,
    parse_registrant_identity,
    previous_content_line,
)

_RULE_KEYS = (
    "rule_12d2_2_a1",
    "rule_12d2_2_a2",
    "rule_12d2_2_a3",
    "rule_12d2_2_a4",
    "rule_12d2_2_b",
    "rule_12d2_2_c",
)
_INSTRUCTION_KEYS = (
    "section_12b_effective",
    "section_12g_effective",
    "regulation_a_concurrent",
)

_FILE_NUMBER_RE = re.compile(
    r"commission file (?:numbers?|no\.?)[:\s]*([0-9][0-9a-z]*(?:-[0-9a-z]+)+|[0-9]+)",
    re.IGNORECASE,
)
_FILE_CAPTION_RE = re.compile(r"commission file (?:numbers?|no\.?)", re.IGNORECASE)
_REGISTRANT_LABEL_RE = re.compile(r"exact name of registrant", re.IGNORECASE)
_ISSUER_LABEL_RE = re.compile(r"exact name of issuer", re.IGNORECASE)
_GENERIC_NAME_LABEL_RE = re.compile(r"exact name of", re.IGNORECASE)
_CLASS_LABEL_RE = re.compile(r"description of class of securities", re.IGNORECASE)
_RELATED_FILE_RE = re.compile(
    r"file number to which this form relates[:\s]*([0-9][0-9-]*)",
    re.IGNORECASE,
)
_CLASS_TABLE_HEADER_RE = re.compile(r"title of each class", re.IGNORECASE)
_TABLE_STOP_PHRASES = (
    "if this form relates",
    "securities to be registered pursuant to section 12(g)",
    "information required in registration statement",
    "securities act registration statement",
)


def _name_before_label(lines: list[str], label_re: re.Pattern[str]) -> str | None:
    for index, line in enumerate(lines):
        match = label_re.search(line)
        if match is None:
            continue
        prefix = line[: match.start()].strip(" ,-(")
        if len(prefix) >= 3:
            name = parse_registrant_identity(prefix).name
            if name is not None:
                return name
        cursor = index
        for _ in range(4):
            previous = previous_content_line(lines, cursor)
            if previous is None:
                break
            cursor, text = previous
            name = parse_registrant_identity(text).name
            if name is not None:
                return name
    return None


def _extract_class_pairs(lines: list[str]) -> list[dict[str, str]]:
    pairs: list[dict[str, str]] = []
    in_table = False
    pending: str | None = None
    for line in lines:
        lowered = line.lower()
        if _CLASS_TABLE_HEADER_RE.search(line):
            in_table = True
            pending = None
            continue
        if not in_table:
            continue
        if any(phrase in lowered for phrase in _TABLE_STOP_PHRASES):
            break
        text = line.strip(" -–—")
        if not text or "name of each exchange" in lowered:
            continue
        if pending is None:
            pending = text
        else:
            pairs.append({"class_title": pending, "exchange": text})
            pending = None
        if len(pairs) >= 6:
            break
    return pairs


def analyze_form_12reg_review_case(
    case_dir: Path, record: dict[str, Any]
) -> dict[str, Any] | None:
    """Analyze one cluster review case with kind-specific cover fields."""
    resolved_form = str(record.get("form") or record.get("family") or "8-A")
    canonical = resolve_alias(resolved_form) or resolved_form.strip().upper()
    kind = kind_of(resolved_form)
    text_path = locate_text_artifact(case_dir)
    if text_path is None:
        return None
    try:
        text = text_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    rep = analyze_form_case(
        case_dir, record, form=resolved_form, family=canonical, text=text
    )
    if rep is None:
        return None
    lines = text.splitlines()
    start = rep["boundary"]["start_line"] or 0
    end = rep["boundary"]["end_line"] or 0
    cover_text = "\n".join(lines[start:end]) if end > start else ""
    file_number = extract_commission_file_number(
        cover_text, number_pattern=_FILE_NUMBER_RE, caption_pattern=_FILE_CAPTION_RE
    ) or extract_commission_file_number(
        text, number_pattern=_FILE_NUMBER_RE, caption_pattern=_FILE_CAPTION_RE
    )
    states = rep["checkmarks"].get("candidate_states", {})
    fields: dict[str, Any] = {
        "kind": kind.value,
        "commission_file_number": file_number,
    }
    if kind is Form12RegKind.NOTIFICATION:
        fields["issuer_name"] = (
            _name_before_label(lines, _ISSUER_LABEL_RE)
            or _name_before_label(lines, _REGISTRANT_LABEL_RE)
            or _name_before_label(lines, _GENERIC_NAME_LABEL_RE)
        )
        fields["class_description"] = _name_before_label(lines, _CLASS_LABEL_RE)
        for key in _RULE_KEYS:
            rep["checkmarks"][key] = states.get(key) == "checked"
        if not file_number:
            rep["anomalies"].append(
                anomaly_record(
                    "missing_commission_file_number",
                    "no commission file number matched on the cover",
                )
            )
        if not fields["issuer_name"]:
            rep["anomalies"].append(
                anomaly_record(
                    "missing_issuer_name",
                    "no issuer name resolved from the cover caption",
                )
            )
        if not any(rep["checkmarks"][key] for key in _RULE_KEYS):
            rep["anomalies"].append(
                anomaly_record(
                    "no_rule_provision_checked",
                    "none of the six rule provisions resolved as checked",
                )
            )
    else:
        fields["registrant_name"] = _name_before_label(
            lines, _REGISTRANT_LABEL_RE
        ) or _name_before_label(lines, _GENERIC_NAME_LABEL_RE)
        fields["security_classes"] = _extract_class_pairs(lines)
        related = _RELATED_FILE_RE.search(text)
        fields["related_file_number"] = related.group(1) if related else None
        if canonical == "8-A":
            for key in _INSTRUCTION_KEYS:
                rep["checkmarks"][key] = states.get(key) == "checked"
        if not fields["registrant_name"]:
            rep["anomalies"].append(
                anomaly_record(
                    "missing_registrant_name",
                    "no registrant name resolved from the cover caption",
                )
            )
        if not fields["security_classes"] and "section 12(g)" not in text.lower():
            rep["anomalies"].append(
                anomaly_record(
                    "missing_security_class",
                    "no class/exchange pairs resolved from the cover table",
                )
            )
    rep["form_12reg"] = fields
    return rep


def summarize_form_12reg_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate individual cluster case analyses into an overall summary."""
    summary = summarize_form_cases(case_reports)
    total = summary.get("case_count", 0)
    if not total:
        return summary

    def fields_of(rep: dict[str, Any]) -> dict[str, Any]:
        return rep.get("form_12reg", {})

    kinds: dict[str, int] = {}
    for rep in case_reports:
        kind = str(fields_of(rep).get("kind") or "unknown")
        kinds[kind] = kinds.get(kind, 0) + 1
    summary["form_12reg_scorecard"] = {
        "kind_counts": kinds,
        "commission_file_number_count": sum(
            1 for r in case_reports if fields_of(r).get("commission_file_number")
        ),
        "issuer_or_registrant_name_count": sum(
            1
            for r in case_reports
            if fields_of(r).get("issuer_name") or fields_of(r).get("registrant_name")
        ),
        "class_description_count": sum(
            1 for r in case_reports if fields_of(r).get("class_description")
        ),
        "cases_with_class_pairs": sum(
            1 for r in case_reports if fields_of(r).get("security_classes")
        ),
        "total_class_pairs": sum(
            len(fields_of(r).get("security_classes") or []) for r in case_reports
        ),
        "related_file_number_count": sum(
            1 for r in case_reports if fields_of(r).get("related_file_number")
        ),
        "rule_checked_counts": {
            key: sum(1 for r in case_reports if r.get("checkmarks", {}).get(key))
            for key in _RULE_KEYS
        },
        "instruction_checked_counts": {
            key: sum(1 for r in case_reports if r.get("checkmarks", {}).get(key))
            for key in _INSTRUCTION_KEYS
        },
    }
    return summary


analyze_case = analyze_form_12reg_review_case
summarize_cases = summarize_form_12reg_cases

__all__ = [
    "analyze_case",
    "analyze_form_12reg_review_case",
    "summarize_cases",
    "summarize_form_12reg_cases",
]
