from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET

from edgar_sec.engine.forms.common.extraction import local_name
from edgar_sec.engine.forms.common.statutory import (
    HEADER_LEAK_RE,
    STATUTORY_PAGE_ARTIFACT_RE,
)
from edgar_sec.engine.forms.beneficial_ownership.provenance_analysis import (
    analyze_extraction_provenance,
)
from edgar_sec.engine.forms.beneficial_ownership.cover_value_diagnostics import (
    cover_field_has_layout_residue,
    has_descriptive_numeric_qualifier,
    is_eight_character_cusip,
    is_unavailable_cusip,
    cusip_page_residue_match,
    parsed_field_boilerplate_match,
)
from edgar_sec.engine.forms.beneficial_ownership.vocabulary import (
    CATEGORICAL_FIELDS,
    CHECKBOX_FIELDS,
    COVER_VALUE_FIELDS,
    FIELD_TAGS,
)
from edgar_sec.engine.forms.beneficial_ownership.field_observations import (
    empty_field_observations,
    field_observations,
)
from edgar_sec.engine.forms.common.signatures import (
    clean_signature_name,
    is_valid_signature_name,
)
from edgar_sec.engine.forms.common.unparsed import load_unparsed_sections
from edgar_sec.engine.forms.beneficial_ownership.schema_analysis import (
    analyze_schema_xml,
)
from edgar_sec.engine.document.signatures import (
    CONFORMED_SIGNATURE_RE,
    RE_SIGNATURE_DATE_LINE,
    RE_SIGNATURE_HEADING,
)
from edgar_sec.foundation.regex.builder import build_alternation

_SCHEDULE_13D_NS = "http://www.sec.gov/edgar/schedule13D"
_SCHEDULE_13G_NS = "http://www.sec.gov/edgar/schedule13G"
_ALLOWED_NAMESPACES = {_SCHEDULE_13D_NS, _SCHEDULE_13G_NS}

_NUMERIC_COVER_RE = re.compile(
    r"(?i)^\s*[-_:]*\s*(?:(?:approximately|approx\.?)\s*)?\$?(?:\d[\d,\s]*(?:\.\d+)?|--?0--?|--?|NONE|NIL|N/?A|NOT\s+APPLICABLE)\s*(?:\(\s*(?:SEE\s+)?ITEM\s+\d+[A-Z]?\s*\)\s*)*(?:\(\s*[A-Z0-9]+\s*\)\s*)*[*†‡]*[-_:.,\s]*$"
)
_QUALIFIED_NUMERIC_SUFFIX_ALT = build_alternation(
    (
        r"shares?\s+of\s+(?:common\s+)?stock",
        r"of\s+common\s+stock",
        r"based\s+on\b",
    ),
    compact=False,
)
_QUALIFIED_NUMERIC_COVER_RE = re.compile(
    rf"(?i)^\s*[-_:]*\s*\d[\d,\s]*(?:\.\d+)?\s*%?\s+(?:{_QUALIFIED_NUMERIC_SUFFIX_ALT}).*$"
)
_PERCENT_COVER_RE = re.compile(
    r"(?i)^\s*[-_:]*\s*(?:(?:approximately|approx\.?)\s*)?\$?\d[\d,\s]*(?:\.\d+)?\s*%?\d{0,2}[A-Z]?\s*(?:\(\s*(?:SEE\s+)?ITEM\s+\d+[A-Z]?\s*\)\s*)*(?:\(\s*[A-Z0-9]+\s*\)\s*)*[*†‡]*[-_:.,\s]*$"
)
_CUSIP_RE = re.compile(r"(?i)^[0-9A-Z*@#]{9}$")
_MULTI_CLASS_VALUE_RE = re.compile(r"(?i)\bSERIES\s+[A-Z]\b.{0,180}?\d[\d,]*(?:\.\d+)?")
_ITEM_SUBSECTION_RE = re.compile(r"(?im)^\s*\([a-f]\)\s")
_NARRATIVE_FIELD_NAMES = {f"item{number}" for number in range(1, 11)}


def _text(element: ET.Element) -> str:
    return " ".join(part.strip() for part in element.itertext() if part.strip())


def _elements(root: ET.Element, names: tuple[str, ...]) -> list[ET.Element]:
    wanted = set(names)
    return [element for element in root.iter() if local_name(element.tag) in wanted]


def _source_has_signature(source_text: str) -> bool:
    for heading in RE_SIGNATURE_HEADING.finditer(source_text):
        section = source_text[heading.end() : heading.end() + 3000]
        if CONFORMED_SIGNATURE_RE.search(section):
            return True
        lines = section.splitlines()
        for index, line in enumerate(lines):
            if not RE_SIGNATURE_DATE_LINE.match(line):
                continue
            for name_line in lines[index + 1 : index + 5]:
                candidate = clean_signature_name(name_line)
                if is_valid_signature_name(candidate):
                    return True
    return False


def _boilerplate_match(field: str, value: str) -> re.Match[str] | None:
    if field in _NARRATIVE_FIELD_NAMES or field == "signature":
        return None
    return parsed_field_boilerplate_match(value)


def _is_narrative_element(
    element: ET.Element, parents: dict[ET.Element, ET.Element]
) -> bool:
    current = element
    while current in parents:
        current = parents[current]
        if local_name(current.tag).casefold() in _NARRATIVE_FIELD_NAMES:
            return True
    return False


def _analyze_xml(
    xml_text: str,
    accession: str,
    expected_family: str = "",
    source_text: str | None = None,
    unparsed_records: tuple[dict[str, object], ...] = (),
    unparsed_error: str | None = None,
) -> dict[str, Any]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as error:
        family = "13G" if "13G" in expected_family.upper() else "13D"
        return {
            "accession": accession,
            "form": family,
            "family": family,
            "error": "malformed_xml",
            "field_observations": empty_field_observations(FIELD_TAGS),
            "anomalies": [
                {
                    "accession": accession,
                    "kind": "malformed_xml",
                    "detail": str(error),
                }
            ],
            "review_signals": [],
            "value_frequencies": {},
            "unparsed_sections": [],
            "date_normalization_evidence": [],
            "extraction_coverage": None,
        }

    anomalies: list[dict[str, Any]] = []
    review_signals: list[dict[str, Any]] = []
    parents = {child: parent for parent in root.iter() for child in parent}
    namespace, _, _ = root.tag.rpartition("}")
    ns_uri = namespace.removeprefix("{")
    root_name = local_name(root.tag)
    family = (
        "13G"
        if ns_uri == _SCHEDULE_13G_NS
        or (not ns_uri and "13G" in expected_family.upper())
        else "13D"
    )
    expected = "13G" if "13G" in expected_family.upper() else "13D"
    if root_name != "edgarSubmission" or ns_uri not in _ALLOWED_NAMESPACES:
        anomalies.append(
            {
                "accession": accession,
                "kind": "invalid_document_envelope",
                "value": root.tag,
                "detail": "root is not a recognized SEC beneficial ownership edgarSubmission envelope",
            }
        )
    if expected_family and family != expected:
        anomalies.append(
            {
                "accession": accession,
                "kind": "form_family_mismatch",
                "value": family,
                "detail": f"rendered XML family {family} differs from expected {expected}",
            }
        )
    anomalies.extend(analyze_schema_xml(root, accession, family))

    direct_children = {local_name(child.tag) for child in root}
    for required in ("headerData", "formData"):
        if required not in direct_children:
            anomalies.append(
                {
                    "accession": accession,
                    "kind": f"missing_{required}",
                    "detail": f"Required XML envelope section {required!r} is missing",
                }
            )

    item_containers = _elements(root, ("items1To7", "narrativeItems", "items"))
    for container in item_containers:
        seen_items: set[str] = set()
        for child in container:
            name = local_name(child.tag).casefold()
            if name not in {f"item{number}" for number in range(1, 11)}:
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": "unknown_narrative_item",
                        "value": name,
                        "detail": "narrative items container holds unrecognized item tag",
                    }
                )
            elif name in seen_items:
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": "duplicate_narrative_item",
                        "value": name,
                        "detail": "narrative items container holds duplicate item",
                    }
                )
            seen_items.add(name)
            item_text = _text(child)
            if (
                RE_SIGNATURE_HEADING.search(item_text)
                and CONFORMED_SIGNATURE_RE.search(item_text)
                and not any(
                    _text(element) for element in _elements(root, ("signature",))
                )
            ):
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": "signature_contained_in_narrative_item",
                        "field": name,
                        "char_length": len(item_text),
                        "snippet": item_text[:240],
                        "detail": "signature evidence is serialized inside a narrative item",
                    }
                )
            if name == "item2":
                for element in child:
                    if (
                        local_name(element.tag) == "filingPersonName"
                        and len(_text(element)) > 240
                        and len(_ITEM_SUBSECTION_RE.findall(_text(element))) >= 2
                    ):
                        value = _text(element)
                        anomalies.append(
                            {
                                "accession": accession,
                                "kind": "flattened_narrative_field",
                                "field": "item2.filingPersonName",
                                "char_length": len(value),
                                "snippet": value[:240],
                                "detail": "Item 2 subparts are collapsed into the filing-person name field",
                            }
                        )
            elif name == "item5":
                for element in child:
                    if (
                        local_name(element.tag) == "percentageOfClassSecurities"
                        and len(_text(element)) > 240
                        and len(_ITEM_SUBSECTION_RE.findall(_text(element))) >= 2
                    ):
                        value = _text(element)
                        anomalies.append(
                            {
                                "accession": accession,
                                "kind": "flattened_narrative_field",
                                "field": "item5.percentageOfClassSecurities",
                                "char_length": len(value),
                                "snippet": value[:240],
                                "detail": "Item 5 subsections are collapsed into the percentage field",
                            }
                        )

    source_has_signature = bool(source_text and _source_has_signature(source_text))
    xml_has_signature = any(
        _text(element) for element in _elements(root, ("signature",))
    )
    if source_has_signature and not xml_has_signature:
        anomalies.append(
            {
                "accession": accession,
                "kind": "signature_missing_from_xml",
                "detail": "normalized source contains signature evidence but XML has no signature value",
            }
        )

    for name in COVER_VALUE_FIELDS:
        for element in _elements(root, FIELD_TAGS[name]):
            value = _text(element)
            boilerplate = (
                None
                if _is_narrative_element(element, parents)
                else _boilerplate_match(name, value)
            )
            if boilerplate is not None:
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": "boilerplate_in_parsed_field",
                        "field": name,
                        "value": value,
                        "matched_text": boilerplate.group(0),
                        "detail": f"parsed field {name!r} contains filing boilerplate",
                    }
                )
            elif value and cover_field_has_layout_residue(name, value):
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": "cover_field_contamination",
                        "field": name,
                        "value": value,
                        "detail": f"cover field {name!r} contains label or table-border residue",
                    }
                )

    for field in (
        "soleVotingPower",
        "sharedVotingPower",
        "soleDispositivePower",
        "sharedDispositivePower",
        "aggregateAmountOwned",
        "percentOfClass",
    ):
        for element in _elements(root, FIELD_TAGS[field]):
            value = _text(element)
            if (
                not _is_narrative_element(element, parents)
                and _boilerplate_match(field, value) is not None
            ):
                continue
            contamination = cover_field_has_layout_residue(field, value)
            value_pattern = (
                _PERCENT_COVER_RE if field == "percentOfClass" else _NUMERIC_COVER_RE
            )
            if not value or contamination or value_pattern.fullmatch(value):
                continue
            multi_class = len(_MULTI_CLASS_VALUE_RE.findall(value)) >= 2
            if (
                multi_class
                or _QUALIFIED_NUMERIC_COVER_RE.fullmatch(value)
                or has_descriptive_numeric_qualifier(value)
            ):
                review_signals.append(
                    {
                        "accession": accession,
                        "kind": (
                            "multi_class_numeric_cover_value"
                            if multi_class
                            else "qualified_numeric_cover_value"
                        ),
                        "field": field,
                        "char_length": len(value),
                        "snippet": value[:240],
                    }
                )
            else:
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": "invalid_numeric_cover_value",
                        "field": field,
                        "value": value,
                        "detail": f"cover field {field!r} is not a recognizable numeric value",
                    }
                )

    for element in _elements(root, FIELD_TAGS["issuerCusip"]):
        value = _text(element)
        normalized = value.replace(" ", "").replace("-", "")
        if is_unavailable_cusip(value):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "unavailable_cusip_emitted",
                    "field": "issuerCusip",
                    "value": value,
                    "detail": "a missing-CUSIP marker is emitted as a CUSIP value",
                }
            )
        elif cusip_page_residue_match(value):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "cover_field_contamination",
                    "field": "issuerCusip",
                    "value": value,
                    "detail": "issuer CUSIP contains page or filing-header residue",
                }
            )
        elif value and is_eight_character_cusip(normalized):
            review_signals.append(
                {
                    "accession": accession,
                    "kind": "short_cusip_value",
                    "field": "issuerCusip",
                    "value": value,
                    "detail": "source provides an eight-character CUSIP without a check digit",
                }
            )
        elif value and not _CUSIP_RE.fullmatch(normalized):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "invalid_cusip",
                    "field": "issuerCusip",
                    "value": value,
                    "detail": "issuer CUSIP does not contain nine valid characters",
                }
            )

    for name in CHECKBOX_FIELDS:
        for element in _elements(root, (name,)):
            value = _text(element).upper()
            if value and value not in {"Y", "N"}:
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": "invalid_checkbox_value",
                        "field": name,
                        "value": value,
                        "detail": "Beneficial ownership checkbox value is neither Y nor N",
                    }
                )

    observations = field_observations(root, FIELD_TAGS)
    field_values = {
        field: [
            value for element in _elements(root, names) if (value := _text(element))
        ]
        for field, names in FIELD_TAGS.items()
    }
    value_frequencies = {
        name: [_text(element) for element in _elements(root, (name,)) if _text(element)]
        for name in CATEGORICAL_FIELDS
    }
    unparsed_sections = []
    date_normalization_evidence = []
    for record in unparsed_records:
        value = str(record.get("content", ""))
        role = str(record.get("role", ""))
        if role.startswith("normalization.date:"):
            evidence = {
                "field": role.removeprefix("normalization.date:"),
                "content": value,
                "reported_year_anchor": record.get("reported_year_anchor"),
            }
            for key in ("start_offset", "end_offset"):
                if key in record:
                    evidence[key] = record[key]
            date_normalization_evidence.append(evidence)
            continue
        is_boilerplate = bool(STATUTORY_PAGE_ARTIFACT_RE.search(value))
        section = {
            "accession": accession,
            "role": role,
            "content_type": record.get("content_type", "text/plain"),
            "char_length": len(value),
            "snippet": " ".join(value.split())[:240],
            "is_boilerplate": is_boilerplate,
        }
        for key in ("table_index", "start_offset", "end_offset"):
            if key in record:
                section[key] = record[key]
        unparsed_sections.append(section)
        if role in {"item2.unparsed", "item5.unparsed"} and value.strip():
            review_signals.append(
                {
                    "accession": accession,
                    "kind": "unparsed_narrative_content",
                    "field": role,
                    "char_length": len(value),
                    "snippet": " ".join(value.split())[:240],
                }
            )
        if role.startswith("normalization.unresolved:"):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "unresolved_scalar_normalization",
                    "field": role.removeprefix("normalization.unresolved:"),
                    "snippet": " ".join(value.split())[:240],
                    "detail": "recognized scalar evidence could not be normalized to its XML type",
                }
            )

    provenance_anomalies, extraction_coverage = analyze_extraction_provenance(
        root, source_text, accession, required=False
    )
    anomalies.extend(provenance_anomalies)
    if unparsed_error is not None:
        anomalies.append(
            {
                "accession": accession,
                "kind": "invalid_unparsed_sections_sidecar",
                "detail": unparsed_error,
            }
        )
    return {
        "accession": accession,
        "form": family,
        "family": family,
        "error": None,
        "field_observations": observations,
        "field_values": field_values,
        "anomalies": anomalies,
        "review_signals": review_signals,
        "value_frequencies": value_frequencies,
        "unparsed_sections": unparsed_sections,
        "date_normalization_evidence": date_normalization_evidence,
        "extraction_coverage": extraction_coverage,
    }


def _empty_observations() -> dict[str, dict[str, int]]:
    return {
        field: {"occurrences": 0, "populated_occurrences": 0, "blank_occurrences": 0}
        for field in FIELD_TAGS
    }


def analyze_case(case_dir: Path, record: dict[str, Any]) -> dict[str, Any] | None:
    xml_path = case_dir / "operations" / "render_to_xml.xml"
    if (
        not xml_path.is_file()
        and not (case_dir / "operations" / "render_to_txt.txt").is_file()
    ):
        return None
    accession = str(record.get("accession", case_dir.name))
    expected_family = str(record.get("form", record.get("family", "")))
    if not xml_path.is_file():
        return {
            "accession": accession,
            "form": "13G" if "13G" in expected_family.upper() else "13D",
            "family": "13G" if "13G" in expected_family.upper() else "13D",
            "error": "missing_rendered_xml",
            "field_observations": empty_field_observations(FIELD_TAGS),
            "anomalies": [
                {
                    "accession": accession,
                    "kind": "missing_rendered_xml",
                    "detail": "text rendering exists but render_to_xml.xml is absent",
                }
            ],
            "review_signals": [],
            "value_frequencies": {},
            "unparsed_sections": [],
            "date_normalization_evidence": [],
            "extraction_coverage": None,
        }
    source_text: str | None = None
    text_path = case_dir / "operations" / "render_to_txt.txt"
    if text_path.is_file():
        try:
            source_text = text_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            source_text = None
    try:
        xml_text = xml_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return {
            "accession": accession,
            "form": "13G" if "13G" in expected_family.upper() else "13D",
            "family": "13G" if "13G" in expected_family.upper() else "13D",
            "error": "unreadable_xml",
            "field_observations": empty_field_observations(FIELD_TAGS),
            "anomalies": [
                {
                    "accession": accession,
                    "kind": "unreadable_xml",
                    "detail": str(error),
                }
            ],
            "review_signals": [],
            "value_frequencies": {},
            "unparsed_sections": [],
            "date_normalization_evidence": [],
            "extraction_coverage": None,
        }
    operations_dir = case_dir / "operations"
    unparsed_records: tuple[dict[str, object], ...] = ()
    unparsed_error: str | None = None
    try:
        root = ET.fromstring(xml_text)
        unparsed_records = load_unparsed_sections(case_dir, root)
    except ET.ParseError:
        pass
    except ValueError as error:
        unparsed_error = str(error)
    except OSError as error:
        unparsed_error = str(error)
    return _analyze_xml(
        xml_text,
        accession,
        expected_family,
        source_text,
        unparsed_records=unparsed_records,
        unparsed_error=unparsed_error,
    )


def summarize_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
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


__all__ = ["analyze_case", "summarize_cases"]
