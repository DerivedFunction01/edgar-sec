"""Semantic review analysis for SEC Regulation A filings."""

from __future__ import annotations

from collections import Counter
import re
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.forms.families.form_rega.models import RegAKind
from edgar_sec.domain.forms.families.form_rega.taxonomy import (
    REGA_SUBMISSION_TYPES,
    kind_of_form,
)
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
from edgar_sec.engine.forms.form_rega.xml_parser import parse_rega_xml

_CORE_FIELDS = (
    "submissionType",
    "filerCik",
    "issuerName",
    "commissionFileNumber",
)

_FILE_NUMBER_RE = re.compile(
    r"commission file (?:numbers?|no\.?)[:\s]*(024-[0-9]+)",
    re.IGNORECASE,
)
_FILE_CAPTION_RE = re.compile(r"commission file (?:numbers?|no\.?)", re.IGNORECASE)
_BARE_FILE_NUMBER_RE = re.compile(r"\b024-[0-9]{4,6}\b")
_ISSUER_LABEL_RE = re.compile(
    r"exact name of issuer as specified in its charter", re.IGNORECASE
)
_REGISTRANT_LABEL_RE = re.compile(
    r"exact name of registrant as specified in its charter", re.IGNORECASE
)
_PERIOD_END_RE = re.compile(r"semiannual period ended:?\s*(.+)", re.IGNORECASE)
_FS_INDEX_PHRASES = (
    "index to financial statements",
    "index to consolidated financial statements",
    "financial statements index",
)


def _missing_report(case_id: str, accession: str, anomaly: str) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "accession_number": accession,
        "core_fields": {f: False for f in _CORE_FIELDS},
        "anomalies": [anomaly],
        "review_signals": ["xml_missing"],
        "blank_fields": {},
        "unparsed_sections": [],
        "form_rega": {},
    }


def analyze_rega_xml_case(
    case_dir: Path,
    record: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Analyze a single Reg A XML review case and return semantic metrics."""
    target_xml = case_dir / "operations" / "render_to_xml.xml"
    if not target_xml.exists():
        extracted = case_dir / "extracted.xml"
        if extracted.exists():
            target_xml = extracted
    accession = (
        str(record.get("accession", ""))
        if record is not None
        else case_dir.name.split("--")[0]
    )
    if not target_xml.exists():
        return _missing_report(case_dir.name, accession, "missing_extracted_xml")
    raw = target_xml.read_bytes()
    try:
        ET.fromstring(raw)
    except ET.ParseError as exc:
        report = _missing_report(case_dir.name, accession, f"xml_parse_error: {exc}")
        report["review_signals"] = ["corrupt_xml"]
        return report
    doc = parse_rega_xml(raw)
    if doc is None:
        return _missing_report(case_dir.name, accession, "missing_submission_document")
    fields = {
        "submission_type": doc.submission_type,
        "kind": doc.kind.value,
        "filer_ciks": list(doc.filer_ciks),
        "issuer_name": doc.issuer_name,
        "issuer_cik": doc.issuer_cik,
        "commission_file_number": doc.commission_file_number,
        "jurisdiction": doc.jurisdiction,
        "tier": doc.tier,
        "total_aggregate_offering": doc.total_aggregate_offering,
        "has_summary_block": doc.has_summary_block,
        "has_certification": doc.has_certification,
    }
    core_status = {
        "submissionType": bool(doc.submission_type),
        "filerCik": bool(doc.filer_ciks),
        "issuerName": bool(doc.issuer_name),
        "commissionFileNumber": bool(doc.commission_file_number),
    }
    anomalies: list[str] = []
    if not doc.submission_type:
        anomalies.append("missing_submission_type")
    elif doc.submission_type.strip().upper() not in REGA_SUBMISSION_TYPES:
        anomalies.append(f"submission_type_off_vocabulary: {doc.submission_type}")
    if doc.kind is RegAKind.UNKNOWN:
        anomalies.append("unknown_kind")
    if record is not None and record.get("form"):
        expected = kind_of_form(str(record["form"]))
        if expected is not RegAKind.UNKNOWN and doc.kind is not expected:
            anomalies.append(
                f"kind_form_mismatch: header {doc.submission_type} vs form {record['form']}"
            )
    if not doc.filer_ciks:
        anomalies.append("missing_filer_cik")
    if not doc.issuer_name:
        anomalies.append("missing_issuer_name")
    return {
        "case_id": case_dir.name,
        "accession_number": accession,
        "core_fields": core_status,
        "anomalies": anomalies,
        "review_signals": [],
        "blank_fields": {f: 1 for f, ok in core_status.items() if not ok},
        "unparsed_sections": [],
        "form_rega": fields,
    }


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


_WITHDRAWAL_OBJECTS = (
    "offering statement",
    "offering circular",
    "registration statement",
    "form 1-a",
    "post-qualification amendment",
    "post qualification amendment",
    "pre-effective amendment",
)


def _has_withdrawal_statement(text: str) -> bool:
    """Rule 477 letters name the withdrawn document several ways."""
    normalized = " ".join(text.lower().split())
    return "withdraw" in normalized and any(
        obj in normalized for obj in _WITHDRAWAL_OBJECTS
    )


def _letter_registrant(lines: list[str]) -> str | None:
    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith("re:"):
            name = parse_registrant_identity(stripped[3:].strip()).name
            if name is not None:
                return name
            break
    for line in lines:
        if line.strip():
            return parse_registrant_identity(line.strip()).name
    return None


def analyze_rega_text_case(
    case_dir: Path, record: dict[str, Any]
) -> dict[str, Any] | None:
    """Analyze one Reg A text review case (1-SA / 1-U reports, 1-A-W letters)."""
    resolved_form = str(record.get("form") or record.get("family") or "")
    canonical = resolve_alias(resolved_form) or resolved_form.strip().upper()
    kind = kind_of_form(resolved_form)
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
    start = rep["boundary"]["start_line"] or 0
    end = rep["boundary"]["end_line"] or 0
    cover_text = "\n".join(lines[start:end]) if end > start else ""
    file_number = extract_commission_file_number(
        cover_text, number_pattern=_FILE_NUMBER_RE, caption_pattern=_FILE_CAPTION_RE
    ) or extract_commission_file_number(
        text, number_pattern=_FILE_NUMBER_RE, caption_pattern=_FILE_CAPTION_RE
    )
    fields: dict[str, Any] = {"kind": kind.value, "commission_file_number": file_number}
    if kind is RegAKind.WITHDRAWAL:
        fields["registrant_name"] = _letter_registrant(lines)
        fields["withdrawal_statement"] = _has_withdrawal_statement(text)
        if not file_number:
            bare = _BARE_FILE_NUMBER_RE.search(text)
            fields["commission_file_number"] = bare.group(0) if bare else None
            file_number = fields["commission_file_number"]
        if not file_number:
            rep["anomalies"].append(
                anomaly_record(
                    "missing_commission_file_number",
                    "no 024- file number matched in the withdrawal letter",
                )
            )
        if not fields["registrant_name"]:
            rep["anomalies"].append(
                anomaly_record(
                    "missing_registrant_name",
                    "no registrant name resolved from the letter face",
                )
            )
        if not fields["withdrawal_statement"]:
            rep["anomalies"].append(
                anomaly_record(
                    "missing_withdrawal_statement",
                    "no withdrawal-of-offering-statement statement found",
                )
            )
    else:
        fields["issuer_name"] = _name_before_label(
            lines, _ISSUER_LABEL_RE
        ) or _name_before_label(lines, _REGISTRANT_LABEL_RE)
        if not fields["issuer_name"]:
            rep["anomalies"].append(
                anomaly_record(
                    "missing_issuer_name",
                    "no issuer name resolved from the cover caption",
                )
            )
        if kind is RegAKind.SEMI_ANNUAL:
            period = _PERIOD_END_RE.search(cover_text) or _PERIOD_END_RE.search(text)
            fields["fiscal_period_end"] = period.group(1).strip() if period else None
            lowered = text.lower()
            fields["has_fs_index"] = any(p in lowered for p in _FS_INDEX_PHRASES)
    rep["form_rega"] = fields
    return rep


def analyze_case(
    case_dir: Path,
    record: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Analyze one Reg A review case, dispatching on kind and artifact."""
    form = str(record.get("form") or "") if record is not None else ""
    kind = kind_of_form(form) if form else RegAKind.UNKNOWN
    xml_artifact = (case_dir / "operations" / "render_to_xml.xml").exists() or (
        case_dir / "extracted.xml"
    ).exists()
    if xml_artifact or kind in (
        RegAKind.OFFERING,
        RegAKind.ANNUAL_REPORT,
        RegAKind.EXIT_REPORT,
    ):
        return analyze_rega_xml_case(case_dir, record)
    if record is None:
        return None
    return analyze_rega_text_case(case_dir, record)


def _summarize_xml_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    anomaly_counts: Counter[str] = Counter()
    for rep in case_reports:
        anomaly_counts.update(
            a.split(":")[0] if isinstance(a, str) else a["kind"]
            for a in rep.get("anomalies", [])
        )
    kinds: Counter[str] = Counter()
    types: Counter[str] = Counter()
    tiers: Counter[str] = Counter()
    for rep in case_reports:
        fields = rep.get("form_rega", {})
        if fields.get("kind"):
            kinds[fields["kind"]] += 1
        if fields.get("submission_type"):
            types[fields["submission_type"]] += 1
        if fields.get("tier"):
            tiers[fields["tier"]] += 1
    return {
        "case_count": len(case_reports),
        "anomaly_counts": dict(anomaly_counts),
        "form_rega_scorecard": {
            "kind_counts": dict(kinds),
            "submission_type_counts": dict(types),
            "tier_counts": dict(tiers),
            "parsed_count": sum(1 for r in case_reports if r.get("form_rega")),
            "issuer_name_count": sum(
                1 for r in case_reports if r.get("form_rega", {}).get("issuer_name")
            ),
            "commission_file_number_count": sum(
                1
                for r in case_reports
                if r.get("form_rega", {}).get("commission_file_number")
            ),
            "summary_block_count": sum(
                1
                for r in case_reports
                if r.get("form_rega", {}).get("has_summary_block")
            ),
            "certification_count": sum(
                1
                for r in case_reports
                if r.get("form_rega", {}).get("has_certification")
            ),
        },
    }


def summarize_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate individual Reg A case analyses into a summary."""
    if case_reports and "core_fields" in case_reports[0]:
        return _summarize_xml_cases(case_reports)
    summary = summarize_form_cases(case_reports)
    total = summary.get("case_count", 0)
    if not total:
        return summary

    def fields_of(rep: dict[str, Any]) -> dict[str, Any]:
        return rep.get("form_rega", {})

    kinds: dict[str, int] = {}
    for rep in case_reports:
        kind = str(fields_of(rep).get("kind") or "unknown")
        kinds[kind] = kinds.get(kind, 0) + 1
    summary["form_rega_scorecard"] = {
        "kind_counts": kinds,
        "issuer_or_registrant_name_count": sum(
            1
            for r in case_reports
            if fields_of(r).get("issuer_name") or fields_of(r).get("registrant_name")
        ),
        "commission_file_number_count": sum(
            1 for r in case_reports if fields_of(r).get("commission_file_number")
        ),
        "fiscal_period_end_count": sum(
            1 for r in case_reports if fields_of(r).get("fiscal_period_end")
        ),
        "fs_index_count": sum(
            1 for r in case_reports if fields_of(r).get("has_fs_index")
        ),
        "withdrawal_statement_count": sum(
            1 for r in case_reports if fields_of(r).get("withdrawal_statement")
        ),
    }
    return summary


__all__ = [
    "analyze_case",
    "analyze_rega_text_case",
    "analyze_rega_xml_case",
    "summarize_cases",
]
