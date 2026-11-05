"""Form SD review analysis and scorecard aggregation."""

from __future__ import annotations

from functools import cache
import re
from pathlib import Path
from typing import Any

from edgar_sec.domain.forms.families.form_sd.models import SDKind
from edgar_sec.domain.forms.families.form_sd.taxonomy import FORM_SD_ITEMS
from edgar_sec.engine.forms.analysis import (
    analyze_form_case,
    anomaly_record,
    locate_text_artifact,
    reinfer_unmasked_checkmarks,
    summarize_form_cases,
)
from edgar_sec.engine.forms.cover.registrant import (
    extract_commission_file_number,
    parse_registrant_identity,
    previous_content_line,
)
from edgar_sec.engine.forms.sections.items.detector import (
    SectionSequence,
    detect_section_sequence,
)
from edgar_sec.engine.tables.protection.tags import find_table_spans
from edgar_sec.foundation.regex.builder import build_alternation

_RULE_KEYS = ("rule_13p_1", "rule_13q_1")
_ITEM_IDS = tuple(d.item for d in FORM_SD_ITEMS)

_FILE_NUMBER_RE = re.compile(
    r"commission file (?:numbers?|no\.?)[:\s]*([0-9][0-9a-z]*(?:-[0-9a-z]+)+|[0-9]+)",
    re.IGNORECASE,
)
_FILE_CAPTION_RE = re.compile(r"commission file (?:numbers?|no\.?)", re.IGNORECASE)
_REGISTRANT_LABEL_RE = re.compile(r"exact name of (the )?registrant", re.IGNORECASE)
_GENERIC_NAME_LABEL_RE = re.compile(r"exact name of", re.IGNORECASE)
_PERIOD_13P1_RE = re.compile(
    r"rule 13p-1.{0,200}?reporting period from\s+", re.IGNORECASE | re.DOTALL
)
_PERIOD_13Q1_RE = re.compile(
    r"rule 13q-1.{0,200}?fiscal year ended\s+", re.IGNORECASE | re.DOTALL
)
_YEAR_RE = re.compile(r"\d{4}")
_EX_1_01_RE = re.compile(
    r"exhibit\s+1\.01[\s\S]{0,240}?conflict minerals report"
    r"|conflict minerals report[\s\S]{0,240}?exhibit\s+1\.01",
    re.IGNORECASE,
)
_EX_1_02_RE = re.compile(
    r"exhibit\s+1\.02[\s\S]{0,240}?conflict minerals report"
    r"|conflict minerals report[\s\S]{0,240}?exhibit\s+1\.02",
    re.IGNORECASE,
)
_EX_2_01_RE = re.compile(
    r"exhibit\s+2\.01[\s\S]{0,240}?resource extraction"
    r"|resource extraction[\s\S]{0,240}?exhibit\s+2\.01",
    re.IGNORECASE,
)
_EX_2_01_PAYMENT_RE = re.compile(
    r"payment disclosure[\s\S]{0,160}?exhibit\s+2\.01"
    r"|exhibit\s+2\.01[\s\S]{0,160}?payment disclosure",
    re.IGNORECASE,
)
_EX_99_1_RE = re.compile(
    r"payment[\s\S]{0,160}?exhibit\s+99\.1"
    r"|exhibit\s+99\.1[\s\S]{0,160}?payment",
    re.IGNORECASE,
)
_NA_BODY_RE = re.compile(r"^\W*not applicable\W*$", re.IGNORECASE)
_EXHIBIT_HEADER_RE = re.compile(
    r"exhibit\s+(?:" + build_alternation(("number", "index", "no")) + r")\.?",
    re.IGNORECASE,
)
_CMR_PHRASE_RE = re.compile(r"conflict minerals report", re.IGNORECASE)
_REP_PHRASE_RE = re.compile(r"resource extraction", re.IGNORECASE)
_REP_SECTION_RE = re.compile(r"resource extraction issuer disclosure", re.IGNORECASE)
_EIN_RE = re.compile(r"\b\d{2}-\d{7}\b")
_FILE_TOKEN_RE = re.compile(r"\b\d{1,3}-\d{2,6}\b")
_TITLE_RE = re.compile(r"specialized disclosure report", re.IGNORECASE)
_FORM_SD_LINE_RE = re.compile(r"^\s*form sd\s*$", re.IGNORECASE)
_NAME_SKIP_RE = re.compile(
    build_alternation(
        (
            "united states",
            "securities and exchange commission",
            "washington",
            "exact name of",
        )
    ),
    re.IGNORECASE,
)


@cache
def _row_pattern(number: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{re.escape(number)}\b")


def _table_row_companion(
    lines: list[str], number: str, phrase: re.Pattern[str]
) -> bool:
    """True when an exhibit-index row names the companion: a row led
    by the exhibit number, under an exhibit header, carrying the
    companion phrase."""
    row_pattern = _row_pattern(number)
    for index, line in enumerate(lines):
        if not _EXHIBIT_HEADER_RE.search(line):
            continue
        for row in lines[index + 1 : index + 13]:
            if row_pattern.search(row) and phrase.search(row):
                return True
    return False


def _file_number_from_value_row(lines: list[str]) -> str | None:
    """File number from the cover value row: the dashed token beside
    the EIN-shaped token, for faces whose caption fragments in tables."""
    for line in lines:
        ein = _EIN_RE.search(line)
        if ein is None:
            continue
        tokens = [
            match
            for match in _FILE_TOKEN_RE.finditer(line)
            if match.group(0) != ein.group(0)
        ]
        if not tokens:
            continue
        before = [match for match in tokens if match.end() <= ein.start()]
        return (before[-1] if before else tokens[0]).group(0)
    return None


def _name_from_title_block(lines: list[str]) -> str | None:
    """Registrant name from the title block: the first name-shaped
    content line under the form title, for caption-less faces."""
    title_index = next(
        (
            index
            for index, line in enumerate(lines[:25])
            if _TITLE_RE.search(line) or _FORM_SD_LINE_RE.match(line)
        ),
        None,
    )
    if title_index is None:
        return None
    seen = 0
    for line in lines[title_index + 1 : title_index + 16]:
        stripped = line.strip()
        if not stripped or stripped.startswith("<") or stripped.startswith("("):
            continue
        seen += 1
        if seen > 8:
            break
        if (
            _NAME_SKIP_RE.search(stripped)
            or _TITLE_RE.search(stripped)
            or _FORM_SD_LINE_RE.match(stripped)
        ):
            continue
        name = parse_registrant_identity(stripped).name
        if name is not None:
            return name
    return None


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


def _not_applicable_items(
    text: str, lines: list[str], sequence: SectionSequence | None = None
) -> set[str]:
    """Items whose whole body is a not-applicable statement: printed
    on the face but carrying no disclosure of their own."""
    if sequence is None:
        sequence = detect_section_sequence(
            text, family="SD", taxonomy_items=FORM_SD_ITEMS
        )
    omitted: set[str] = set()
    for section in sequence.sections:
        end = section.end_line if section.end_line is not None else len(lines)
        first_body_line = next(
            (
                line.strip()
                for line in lines[section.start_line + 1 : end]
                if line.strip()
            ),
            "",
        )
        if first_body_line and _NA_BODY_RE.match(first_body_line):
            omitted.add(section.item_identifier)
    return omitted


def _classify_kind(
    states: dict[str, Any],
    detected: list[str],
    *,
    rep_section_present: bool,
    na_items: set[str] | None = None,
) -> SDKind:
    p1 = states.get("rule_13p_1") == "checked"
    q1 = states.get("rule_13q_1") == "checked"
    if p1 and q1:
        return SDKind.COMBINED
    if p1:
        return SDKind.CONFLICT_MINERALS
    if q1:
        return SDKind.RESOURCE_EXTRACTION
    # Item fallback: a bare ITEM 2.01 is not evidence — pre-amendment
    # faces print Item 2.01 as the exhibits item, so the resource
    # extraction section vocabulary must corroborate it; a section
    # whose body is solely not-applicable is no evidence either way.
    na_items = na_items or set()
    if "ITEM 2.01" in detected and "ITEM 2.01" not in na_items and rep_section_present:
        return SDKind.RESOURCE_EXTRACTION
    if "ITEM 1.01" in detected and "ITEM 1.01" not in na_items:
        return SDKind.CONFLICT_MINERALS
    return SDKind.UNDETERMINED


def _reporting_period(text: str, states: dict[str, Any]) -> str | None:
    collapsed = " ".join(text.split())
    patterns = (_PERIOD_13P1_RE, _PERIOD_13Q1_RE)
    if states.get("rule_13q_1") == "checked" and states.get("rule_13p_1") != "checked":
        patterns = (_PERIOD_13Q1_RE, _PERIOD_13P1_RE)
    for pattern in patterns:
        match = pattern.search(collapsed)
        if match is None:
            continue
        window = collapsed[match.end() : match.end() + 80]
        years = list(_YEAR_RE.finditer(window))
        if not years:
            continue
        end = years[0].end()
        if len(years) > 1 and " to " in window[: years[-1].end()]:
            end = years[-1].end()
        return window[:end].strip(" ,")
    return None


def analyze_sd_review_case(
    case_dir: Path, record: dict[str, Any]
) -> dict[str, Any] | None:
    """Analyze one SD review case: election, cover fields, companions."""
    resolved_form = str(record.get("form") or record.get("family") or "SD")
    text_path = locate_text_artifact(case_dir)
    if text_path is None:
        return None
    try:
        text = text_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    rep = analyze_form_case(
        case_dir, record, form=resolved_form, family="SD", text=text
    )
    if rep is None:
        return None
    lines = text.splitlines()
    if find_table_spans(text):
        reinfer_unmasked_checkmarks(text, rep, family="SD", case_dir=case_dir)
    full_sequence = None
    if not rep["taxonomy"]["detected_items"] and text:
        # Recovery pass: a fallback boundary can swallow a short SD
        # whole; adopted only when the body-slice pass found nothing.
        full_sequence = detect_section_sequence(
            text, family="SD", taxonomy_items=FORM_SD_ITEMS
        )
        detected = [section.item_identifier for section in full_sequence.sections]
        if detected:
            rep["taxonomy"] = {
                "item_count": len(detected),
                "detected_items": detected,
            }
            rep["anomalies"] = [
                anomaly
                for anomaly in rep["anomalies"]
                if anomaly["kind"] != "no_items_detected"
            ]
    start = rep["boundary"]["start_line"] or 0
    end = rep["boundary"]["end_line"] or 0
    cover_text = "\n".join(lines[start:end]) if end > start else ""
    states = rep["checkmarks"].get("candidate_states", {})
    for key in _RULE_KEYS:
        rep["checkmarks"][key] = states.get(key) == "checked"
    detected = rep["taxonomy"]["detected_items"]
    rep_section_present = bool(_REP_SECTION_RE.search(text))
    boxes_decide = states.get("rule_13p_1") == "checked" or (
        states.get("rule_13q_1") == "checked"
    )
    na_items = (
        set() if boxes_decide else _not_applicable_items(text, lines, full_sequence)
    )
    kind = _classify_kind(
        states, detected, rep_section_present=rep_section_present, na_items=na_items
    )
    cover_lines = lines[start:end] if end > start else lines[:45]
    fields: dict[str, Any] = {
        "kind": kind.value,
        "registrant_name": _name_before_label(lines, _REGISTRANT_LABEL_RE)
        or _name_before_label(lines, _GENERIC_NAME_LABEL_RE)
        or _name_from_title_block(lines),
        "commission_file_number": extract_commission_file_number(
            cover_text,
            number_pattern=_FILE_NUMBER_RE,
            caption_pattern=_FILE_CAPTION_RE,
        )
        or extract_commission_file_number(
            text, number_pattern=_FILE_NUMBER_RE, caption_pattern=_FILE_CAPTION_RE
        )
        or _file_number_from_value_row(cover_lines),
        "reporting_period": _reporting_period(cover_text, states)
        or _reporting_period(text, states),
        "ex_1_01_companion": bool(_EX_1_01_RE.search(text))
        or _table_row_companion(lines, "1.01", _CMR_PHRASE_RE),
        "ex_1_02_companion": bool(_EX_1_02_RE.search(text))
        or _table_row_companion(lines, "1.02", _CMR_PHRASE_RE),
        "ex_2_01_companion": bool(_EX_2_01_RE.search(text))
        or bool(_EX_2_01_PAYMENT_RE.search(text))
        or _table_row_companion(lines, "2.01", _REP_PHRASE_RE),
        "ex_99_1_companion": bool(_EX_99_1_RE.search(text)),
        "item_2_01_exhibits_variant": (
            "ITEM 2.01" in detected and not rep_section_present
        ),
    }
    rep["form_sd"] = fields
    if not fields["registrant_name"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_registrant_name",
                "no registrant name resolved from the cover caption",
            )
        )
    if not fields["commission_file_number"]:
        rep["anomalies"].append(
            anomaly_record(
                "missing_commission_file_number",
                "no commission file number matched on the cover",
            )
        )
    if kind is SDKind.UNDETERMINED:
        rep["anomalies"].append(
            anomaly_record(
                "rule_election_unresolved",
                "neither rule box resolved as checked and no item fallback fired",
            )
        )
    if (
        kind in (SDKind.RESOURCE_EXTRACTION, SDKind.COMBINED)
        and not fields["ex_2_01_companion"]
        and not fields["ex_99_1_companion"]
    ):
        rep["anomalies"].append(
            anomaly_record(
                "missing_ex_2_01_companion",
                "resource-extraction election without an EX-2.01 reference",
            )
        )
    return rep


def summarize_sd_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate individual SD case analyses into an overall summary."""
    summary = summarize_form_cases(case_reports, family="SD")
    total = summary.get("case_count", 0)
    if not total:
        return summary

    def fields_of(rep: dict[str, Any]) -> dict[str, Any]:
        return rep.get("form_sd", {})

    kinds: dict[str, int] = {}
    for rep in case_reports:
        kind = str(fields_of(rep).get("kind") or "unknown")
        kinds[kind] = kinds.get(kind, 0) + 1
    summary["form_sd_scorecard"] = {
        "kind_counts": kinds,
        "registrant_name_count": sum(
            1 for r in case_reports if fields_of(r).get("registrant_name")
        ),
        "commission_file_number_count": sum(
            1 for r in case_reports if fields_of(r).get("commission_file_number")
        ),
        "reporting_period_count": sum(
            1 for r in case_reports if fields_of(r).get("reporting_period")
        ),
        "rule_checked_counts": {
            key: sum(1 for r in case_reports if r.get("checkmarks", {}).get(key))
            for key in _RULE_KEYS
        },
        "ex_1_01_companion_count": sum(
            1 for r in case_reports if fields_of(r).get("ex_1_01_companion")
        ),
        "ex_1_02_companion_count": sum(
            1 for r in case_reports if fields_of(r).get("ex_1_02_companion")
        ),
        "cmr_companion_count": sum(
            1
            for r in case_reports
            if fields_of(r).get("ex_1_01_companion")
            or fields_of(r).get("ex_1_02_companion")
        ),
        "item_2_01_exhibits_variant_count": sum(
            1 for r in case_reports if fields_of(r).get("item_2_01_exhibits_variant")
        ),
        "ex_2_01_companion_count": sum(
            1 for r in case_reports if fields_of(r).get("ex_2_01_companion")
        ),
        "ex_99_1_companion_count": sum(
            1 for r in case_reports if fields_of(r).get("ex_99_1_companion")
        ),
        "item_counts": {
            item: sum(
                1
                for r in case_reports
                if item in r.get("taxonomy", {}).get("detected_items", [])
            )
            for item in _ITEM_IDS
        },
    }
    return summary


analyze_case = analyze_sd_review_case
summarize_cases = summarize_sd_cases

__all__ = [
    "analyze_case",
    "analyze_sd_review_case",
    "summarize_cases",
    "summarize_sd_cases",
]
