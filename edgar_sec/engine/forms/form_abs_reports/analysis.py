"""ABS text reports review analysis and scorecard aggregation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.forms.families.form_abs_reports.models import (
    FormAbsReportsKind,
)
from edgar_sec.domain.forms.families.form_abs_reports.taxonomy import kind_of
from edgar_sec.engine.forms.analysis import (
    analyze_form_case,
    anomaly_record,
    locate_text_artifact,
    reinfer_unmasked_checkmarks,
    summarize_form_cases,
)
from edgar_sec.engine.forms.cover.registrant import (
    parse_registrant_identity,
    previous_content_line,
)
from edgar_sec.engine.tables.protection.tags import find_table_spans

_RULE_KEYS = (
    "rule_15ga_1",
    "rule_15ga_2",
    "no_activity_initial",
    "no_activity_quarterly",
    "no_activity_annual",
)

_FILE_NUMBER_VALUE = r"([0-9][0-9a-z]*(?:-[0-9a-z]+)+|[0-9]+)"
_ISSUING_FILE_RE = re.compile(
    r"commission file number of issuing entity[:\s]*" + _FILE_NUMBER_VALUE,
    re.IGNORECASE,
)
_DEPOSITOR_FILE_RE = re.compile(
    r"commission file number of depositor(?: and sponsor)?[:\s]*" + _FILE_NUMBER_VALUE,
    re.IGNORECASE,
)
_SPONSOR_FILE_RE = re.compile(
    r"commission file number of sponsor[:\s]*" + _FILE_NUMBER_VALUE,
    re.IGNORECASE,
)
_SECURITIZER_FILE_RE = re.compile(
    r"commission file number of securitizer[:\s]*" + _FILE_NUMBER_VALUE,
    re.IGNORECASE,
)
_CIK_VALUE = r"([0-9]{7,10})"
_ISSUING_CIK_RE = re.compile(
    r"central index key (?:number )?of issuing entity[:\s]*" + _CIK_VALUE,
    re.IGNORECASE,
)
_DEPOSITOR_CIK_RE = re.compile(
    r"central index key (?:number )?of depositor(?: and sponsor)?[:\s]*" + _CIK_VALUE,
    re.IGNORECASE,
)
_SPONSOR_CIK_RE = re.compile(
    r"central index key (?:number )?of sponsor[:\s]*" + _CIK_VALUE,
    re.IGNORECASE,
)
_SECURITIZER_CIK_RE = re.compile(
    r"central index key (?:number )?of securitizer[:\s]*" + _CIK_VALUE,
    re.IGNORECASE,
)
_SECURITIZER_FILE_BEFORE_CAPTION_RE = re.compile(
    r"([0-9][0-9a-z]*(?:-[0-9a-z]+)+)"
    r"\s*\(\s*commission file number of securitizer\s*\)",
    re.IGNORECASE,
)
_SECURITIZER_CIK_BEFORE_CAPTION_RE = re.compile(
    r"([0-9]{7,10})\s*\(\s*central index key(?: number)? of securitizer\s*\)",
    re.IGNORECASE,
)
_DATE = r"([a-z]+ \d{1,2}, \d{4})"
_PERIOD_RE = re.compile(
    r"distribution period from[\s\S]{0,48}?" + _DATE + r"\s+to,?\s+" + _DATE,
    re.IGNORECASE,
)
_DATE_LOOSE = r"([a-z]+ ?\d{1,2}\s*, \d{4})"
_PERIOD_LOOSE_RE = re.compile(
    r"distribution period from[\s\S]{0,48}?"
    + _DATE_LOOSE
    + r"\s+to,?\s+"
    + _DATE_LOOSE,
    re.IGNORECASE,
)
_REPORTING_PERIOD_RE = re.compile(
    r"reporting period\s+(?:from\s+)?" + _DATE + r"\s+to\s+" + _DATE,
    re.IGNORECASE,
)
_DATE_OF_REPORT_RE = re.compile(
    r"date of report \(date of earliest event reported\)[:\s]*" + _DATE,
    re.IGNORECASE,
)
_DATE_OF_REPORT_LOOSE_RE = re.compile(
    r"date of report \(date of earliest event reported\)[:\s]*"
    r"([a-z]+ ?\d{1,2}\s*[.,]\s*\d{4})",
    re.IGNORECASE,
)
_DATE_PERIOD_SEP_RE = re.compile(r"\.\s*(?=\d{4}$)")
_PAIR_ABOVE_CAPTION_RE = re.compile(r"(\d{1,3}-[0-9a-z-]+)\s+([0-9]{7,10})")
_PAIR_ABOVE_CIK_ONLY_RE = re.compile(r"(?:(?:N/A|none)\s+)?(\d{10})", re.IGNORECASE)
_PART_CAPTION_RE = re.compile(
    r"\b(?:file|report)\s+(\d+)\s+of\s+(\d+)\b",
    re.IGNORECASE,
)
_PART_BANNER_RE = re.compile(r"file_(\d+)_of_(\d+)", re.IGNORECASE)
_ISSUING_NAME_LABEL_RE = re.compile(r"exact name of issuing entity", re.IGNORECASE)
_DEPOSITOR_NAME_LABEL_RE = re.compile(r"exact name of depositor", re.IGNORECASE)
_TABLE_HEADER_TERMS = ("name of originator", "total assets")


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


_LETTER_DIGIT_RE = re.compile(r"([a-z])(\d)")


def _normalize_period_date(value: str) -> str:
    """Canonical spacing for a period date captured from era typesetting."""
    collapsed = " ".join(value.split()).replace(" ,", ",")
    return _LETTER_DIGIT_RE.sub(r"\1 \2", collapsed)


def _normalize_report_date(value: str) -> str:
    """Canonical form for a date of report captured from era typesetting.

    Era faces print the day/year separator as a period ("February 12. 2016").
    """
    return _DATE_PERIOD_SEP_RE.sub(", ", _normalize_period_date(value.strip()))


def _first_group(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1) if match else None


def _first_cik(pattern: re.Pattern[str], text: str) -> str | None:
    """First CIK match, zero-padded to the canonical ten digits."""
    value = _first_group(pattern, text)
    return value.zfill(10) if value else None


def _caption_pair_above(lines: list[str]) -> tuple[str | None, str | None]:
    """File number / CIK printed as a value row above their captions.

    A caption block starts at either phrase fragment and completes over
    the following lines; the value row sits above the block's first line.
    """
    for index, line in enumerate(lines):
        lowered = line.lower()
        if "commission file" not in lowered and "central index" not in lowered:
            continue
        window = " ".join(lines[index : index + 4]).lower()
        if "commission file" not in window:
            continue
        if "central index key" not in window and "central index number" not in window:
            continue
        if (
            "commission file number" not in window
            and "number of securitizer" not in window
        ):
            continue
        substantive = 0
        for back in range(index - 1, max(index - 10, -1), -1):
            candidate = lines[back].strip()
            if not candidate or set(candidate) <= set("-= "):
                continue
            substantive += 1
            match = _PAIR_ABOVE_CAPTION_RE.search(lines[back])
            if match:
                return match.group(1), match.group(2).zfill(10)
            cik_only = _PAIR_ABOVE_CIK_ONLY_RE.fullmatch(candidate)
            if cik_only:
                return None, cik_only.group(1)
            if substantive >= 2:
                break
    return None, None


def _part_caption_match(lines: list[str]) -> re.Match[str] | None:
    """Part caption in whitespace form or in the underscore filename banner."""
    head = "\n".join(lines[:60])
    return _PART_CAPTION_RE.search(head) or _PART_BANNER_RE.search(head)


def _record_part_caption(record: dict[str, Any]) -> re.Match[str] | None:
    """Part banner from the case record's document path, if it carries one."""
    processing = record.get("processing") or {}
    fixture = record.get("fixture") or {}
    for candidate in (processing.get("effective_path"), fixture.get("target_url")):
        if candidate:
            match = _PART_BANNER_RE.search(str(candidate))
            if match:
                return match
    return None


def _opens_with_table(text: str, lines: list[str]) -> bool:
    """Whether the first substantive rendered line opens a tagged table."""
    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    if first is None:
        return False
    spans = find_table_spans(text)
    return bool(spans) and spans[0].start_line <= first


def _is_table_fragment(
    text: str, lines: list[str], record: dict[str, Any] | None = None
) -> bool:
    """A continuation part: rep-and-warranty table with no form face."""
    head = "\n".join(lines[:60]).lower()
    if "form abs-15g" in head or "check the appropriate box" in head:
        return False
    lowered = text.lower()
    if all(term in lowered for term in _TABLE_HEADER_TERMS):
        return True
    if _PART_CAPTION_RE.search("\n".join(lines[:5])) is not None:
        return True
    if _PART_BANNER_RE.search("\n".join(lines[:10])) is not None:
        return True
    if record is not None and _record_part_caption(record) is not None:
        return _opens_with_table(text, lines)
    return False


def _analyze_distribution(
    rep: dict[str, Any],
    lines: list[str],
    cover_text: str,
    text: str,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "issuing_entity_file_number": _first_group(_ISSUING_FILE_RE, cover_text)
        or _first_group(_ISSUING_FILE_RE, text),
        "issuing_entity_cik": _first_cik(_ISSUING_CIK_RE, cover_text)
        or _first_cik(_ISSUING_CIK_RE, text),
        "depositor_file_number": _first_group(_DEPOSITOR_FILE_RE, cover_text)
        or _first_group(_DEPOSITOR_FILE_RE, text),
        "depositor_cik": _first_cik(_DEPOSITOR_CIK_RE, cover_text)
        or _first_cik(_DEPOSITOR_CIK_RE, text),
        "sponsor_file_number": _first_group(_SPONSOR_FILE_RE, cover_text),
        "issuing_entity_name": _name_before_label(lines, _ISSUING_NAME_LABEL_RE),
        "depositor_name": _name_before_label(lines, _DEPOSITOR_NAME_LABEL_RE),
    }
    period = (
        _PERIOD_RE.search(cover_text)
        or _PERIOD_RE.search(text)
        or _PERIOD_LOOSE_RE.search(cover_text)
        or _PERIOD_LOOSE_RE.search(text)
    )
    fields["distribution_period"] = (
        {
            "from": _normalize_period_date(period.group(1)),
            "to": _normalize_period_date(period.group(2)),
        }
        if period
        else None
    )
    if not fields["issuing_entity_file_number"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_issuing_entity_file_number",
                "no issuing entity file number matched on the cover",
            )
        )
    if not fields["issuing_entity_cik"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_issuing_entity_cik",
                "no issuing entity CIK matched on the cover",
            )
        )
    if not fields["issuing_entity_name"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_issuing_entity_name",
                "no issuing entity name resolved from the cover caption",
            )
        )
    if not fields["distribution_period"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_distribution_period",
                "no distribution period matched on the cover",
            )
        )
    if not fields["depositor_file_number"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_depositor_file_number",
                "no depositor file number matched on the cover",
            )
        )
    return fields


def _analyze_securitizer(
    rep: dict[str, Any],
    lines: list[str],
    cover_text: str,
    text: str,
    record: dict[str, Any],
) -> dict[str, Any]:
    states = rep["checkmarks"].get("candidate_states", {})
    for key in _RULE_KEYS:
        rep["checkmarks"][key] = states.get(key) == "checked"
    lowered = text.lower()
    fields: dict[str, Any] = {
        "table_header_present": all(term in lowered for term in _TABLE_HEADER_TERMS),
        "item_201_detected": "ITEM 2.01" in rep["taxonomy"]["detected_items"],
    }
    if _is_table_fragment(text, lines, record):
        fields["shape"] = "table_fragment"
        caption = _part_caption_match(lines) or _record_part_caption(record)
        fields["part_caption"] = (
            {"index": int(caption.group(1)), "count": int(caption.group(2))}
            if caption
            else None
        )
        return fields
    fields["shape"] = "face"
    file_number = _first_group(_SECURITIZER_FILE_RE, cover_text) or _first_group(
        _SECURITIZER_FILE_RE, text
    )
    cik = _first_cik(_SECURITIZER_CIK_RE, cover_text) or _first_cik(
        _SECURITIZER_CIK_RE, text
    )
    if not file_number or not cik:
        pair_file, pair_cik = _caption_pair_above(lines)
        file_number = file_number or pair_file
        cik = cik or pair_cik
    if not file_number:
        file_number = _first_group(
            _SECURITIZER_FILE_BEFORE_CAPTION_RE, cover_text
        ) or _first_group(_SECURITIZER_FILE_BEFORE_CAPTION_RE, text)
    if not cik:
        cik = _first_cik(_SECURITIZER_CIK_BEFORE_CAPTION_RE, cover_text) or _first_cik(
            _SECURITIZER_CIK_BEFORE_CAPTION_RE, text
        )
    fields["securitizer_file_number"] = file_number
    fields["securitizer_cik"] = cik
    date_of_report = _first_group(_DATE_OF_REPORT_RE, cover_text)
    if not date_of_report:
        loose = _first_group(_DATE_OF_REPORT_LOOSE_RE, cover_text)
        date_of_report = _normalize_report_date(loose) if loose else None
    fields["date_of_report"] = date_of_report
    reporting = _REPORTING_PERIOD_RE.search(cover_text)
    fields["reporting_period"] = (
        {"from": reporting.group(1), "to": reporting.group(2)} if reporting else None
    )
    if not file_number:
        rep["anomalies"].append(
            anomaly_record(
                "missing_securitizer_file_number",
                "no securitizer file number matched on the cover",
            )
        )
    if not cik:
        rep["anomalies"].append(
            anomaly_record(
                "missing_securitizer_cik",
                "no securitizer CIK matched on the cover",
            )
        )
    if not (rep["checkmarks"]["rule_15ga_1"] or rep["checkmarks"]["rule_15ga_2"]):
        rep["anomalies"].append(
            anomaly_record(
                "no_obligation_checked",
                "neither the 15Ga-1 nor the 15Ga-2 box resolved as checked",
            )
        )
    return fields


def analyze_form_abs_reports_review_case(
    case_dir: Path, record: dict[str, Any]
) -> dict[str, Any] | None:
    """Analyze one ABS reports review case with kind-specific fields."""
    resolved_form = str(record.get("form") or record.get("family") or "ABS-15G")
    canonical = resolve_alias(resolved_form) or resolved_form.strip().upper()
    kind = kind_of(resolved_form)
    rep = analyze_form_case(case_dir, record, form=resolved_form, family=canonical)
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
        reinfer_unmasked_checkmarks(text, rep, family=canonical)
    start = rep["boundary"]["start_line"] or 0
    end = rep["boundary"]["end_line"] or 0
    cover_text = "\n".join(lines[start:end]) if end > start else "\n".join(lines[:120])
    if kind is FormAbsReportsKind.DISTRIBUTION:
        fields = _analyze_distribution(rep, lines, cover_text, text)
    else:
        fields = _analyze_securitizer(rep, lines, cover_text, text, record)
    fields["kind"] = kind.value
    assessment = (record.get("processing") or {}).get("exhibit_assessment")
    fields["exhibit_assessment"] = assessment
    rep["form_abs_reports"] = fields
    return rep


def summarize_form_abs_reports_cases(
    case_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate individual ABS reports case analyses into a summary."""
    summary = summarize_form_cases(case_reports)
    total = summary.get("case_count", 0)
    if not total:
        return summary

    def fields_of(rep: dict[str, Any]) -> dict[str, Any]:
        return rep.get("form_abs_reports", {})

    distribution = [
        r for r in case_reports if fields_of(r).get("kind") == "distribution"
    ]
    securitizer = [r for r in case_reports if fields_of(r).get("kind") == "securitizer"]
    faces = [r for r in securitizer if fields_of(r).get("shape") == "face"]
    summary["form_abs_reports_scorecard"] = {
        "kind_counts": {
            "distribution": len(distribution),
            "securitizer": len(securitizer),
        },
        "distribution": {
            "issuing_entity_file_number_count": sum(
                1
                for r in distribution
                if fields_of(r).get("issuing_entity_file_number")
            ),
            "issuing_entity_cik_count": sum(
                1 for r in distribution if fields_of(r).get("issuing_entity_cik")
            ),
            "issuing_entity_name_count": sum(
                1 for r in distribution if fields_of(r).get("issuing_entity_name")
            ),
            "depositor_file_number_count": sum(
                1 for r in distribution if fields_of(r).get("depositor_file_number")
            ),
            "distribution_period_count": sum(
                1 for r in distribution if fields_of(r).get("distribution_period")
            ),
        },
        "securitizer": {
            "face_count": len(faces),
            "table_fragment_count": len(securitizer) - len(faces),
            "securitizer_file_number_count": sum(
                1 for r in faces if fields_of(r).get("securitizer_file_number")
            ),
            "securitizer_cik_count": sum(
                1 for r in faces if fields_of(r).get("securitizer_cik")
            ),
            "date_of_report_count": sum(
                1 for r in faces if fields_of(r).get("date_of_report")
            ),
            "reporting_period_count": sum(
                1 for r in faces if fields_of(r).get("reporting_period")
            ),
            "item_201_count": sum(
                1 for r in securitizer if fields_of(r).get("item_201_detected")
            ),
            "table_header_count": sum(
                1 for r in securitizer if fields_of(r).get("table_header_present")
            ),
            "rule_checked_counts": {
                key: sum(1 for r in securitizer if r.get("checkmarks", {}).get(key))
                for key in _RULE_KEYS
            },
        },
    }
    return summary


analyze_case = analyze_form_abs_reports_review_case
summarize_cases = summarize_form_abs_reports_cases

__all__ = [
    "analyze_case",
    "analyze_form_abs_reports_review_case",
    "summarize_cases",
    "summarize_form_abs_reports_cases",
]
