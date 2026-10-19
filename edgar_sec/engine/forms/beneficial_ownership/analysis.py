from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET

from edgar_sec.engine.forms.common.statutory import (
    HEADER_LEAK_RE,
    STATUTORY_PAGE_ARTIFACT_RE,
)
from edgar_sec.foundation.regex.builder import build_alternation

_SCHEDULE_13D_NS = "http://www.sec.gov/edgar/schedule13D"
_SCHEDULE_13G_NS = "http://www.sec.gov/edgar/schedule13G"
_ALLOWED_NAMESPACES = {_SCHEDULE_13D_NS, _SCHEDULE_13G_NS}

_FIELD_TAGS: dict[str, tuple[str, ...]] = {
    "issuerName": ("issuerName",),
    "issuerCusip": ("issuerCusipNumber", "issuerCUSIP"),
    "securitiesClassTitle": ("securitiesClassTitle",),
    "dateOfEvent": ("dateOfEvent",),
    "reportingPersonName": ("reportingPersonName",),
    "memberOfGroup": ("memberOfGroup",),
    "fundType": ("fundType",),
    "legalProceedings": ("legalProceedings",),
    "citizenshipOrOrganization": ("citizenshipOrOrganization",),
    "soleVotingPower": ("soleVotingPower",),
    "sharedVotingPower": ("sharedVotingPower",),
    "soleDispositivePower": ("soleDispositivePower",),
    "sharedDispositivePower": ("sharedDispositivePower",),
    "aggregateAmountOwned": ("aggregateAmountOwned",),
    "isAggregateExcludeShares": ("isAggregateExcludeShares",),
    "percentOfClass": ("percentOfClass",),
    "typeOfReportingPerson": ("typeOfReportingPerson",),
    "item1": ("item1",),
    "item2": ("item2",),
    "item3": ("item3",),
    "item4": ("item4",),
    "item5": ("item5",),
    "item6": ("item6",),
    "item7": ("item7",),
    "item8": ("item8",),
    "item9": ("item9",),
    "item10": ("item10",),
    "signature": ("signature",),
}
_CATEGORICAL_TAGS = (
    "memberOfGroup",
    "fundType",
    "legalProceedings",
    "citizenshipOrOrganization",
    "typeOfReportingPerson",
    "isAggregateExcludeShares",
)
_CHECKBOX_TAGS = ("legalProceedings", "isAggregateExcludeShares")
_COVER_VALUE_FIELDS = (
    "issuerName",
    "reportingPersonName",
    "securitiesClassTitle",
    "citizenshipOrOrganization",
    "soleVotingPower",
    "sharedVotingPower",
    "soleDispositivePower",
    "sharedDispositivePower",
    "aggregateAmountOwned",
    "percentOfClass",
)
_COVER_LABEL_LEAK_ALT = build_alternation(
    (
        "name of reporting person",
        "names of reporting persons",
        "check the appropriate box",
        "source of funds",
        "sec use only",
        "check if disclosure of legal proceedings",
        "citizenship or place of organization",
        "sole voting power",
        "shared voting power",
        "sole dispositive power",
        "shared dispositive power",
        "aggregate amount beneficially owned",
        "owned by each reporting person",
        "percent of class represented",
        "type of reporting person",
        "see instructions",
        "pursuant to items",
    ),
    auto_escape=True,
    compact=True,
)
_COVER_LABEL_LEAK_RE = re.compile(_COVER_LABEL_LEAK_ALT, re.IGNORECASE)
_SEPARATOR_RUN_RE = re.compile(r"[-_]{8,}")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(element: ET.Element) -> str:
    return " ".join(part.strip() for part in element.itertext() if part.strip())


def _elements(root: ET.Element, names: tuple[str, ...]) -> list[ET.Element]:
    wanted = set(names)
    return [element for element in root.iter() if _local_name(element.tag) in wanted]


def _field_observations(root: ET.Element) -> dict[str, dict[str, int]]:
    observations: dict[str, dict[str, int]] = {}
    for field, names in _FIELD_TAGS.items():
        elements = _elements(root, names)
        populated = sum(bool(_text(element)) for element in elements)
        observations[field] = {
            "occurrences": len(elements),
            "populated_occurrences": populated,
            "blank_occurrences": len(elements) - populated,
        }
    return observations


def _analyze_xml(xml_text: str, accession: str) -> dict[str, Any]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as error:
        return {
            "accession": accession,
            "form": "13D",
            "family": "13D",
            "error": "malformed_xml",
            "field_observations": _empty_observations(),
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
        }

    anomalies: list[dict[str, Any]] = []
    namespace, _, root_name = root.tag.rpartition("}")
    ns_uri = namespace.removeprefix("{")
    if root_name != "edgarSubmission" or ns_uri not in _ALLOWED_NAMESPACES:
        anomalies.append(
            {
                "accession": accession,
                "kind": "invalid_document_envelope",
                "value": root.tag,
                "detail": "root is not a recognized SEC beneficial ownership edgarSubmission envelope",
            }
        )

    direct_children = {_local_name(child.tag) for child in root}
    for required in ("headerData", "formData"):
        if required not in direct_children:
            anomalies.append(
                {
                    "accession": accession,
                    "kind": f"missing_{required}",
                    "detail": f"Required XML envelope section {required!r} is missing",
                }
            )

    item_containers = _elements(root, ("items1To7", "narrativeItems"))
    for container in item_containers:
        seen_items: set[str] = set()
        for child in container:
            name = _local_name(child.tag)
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

    for name in _COVER_VALUE_FIELDS:
        for element in _elements(root, _FIELD_TAGS[name]):
            value = _text(element)
            if value and (
                HEADER_LEAK_RE.search(value)
                or _COVER_LABEL_LEAK_RE.search(value)
                or _SEPARATOR_RUN_RE.search(value)
            ):
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": "cover_field_contamination",
                        "field": name,
                        "value": value,
                        "detail": f"cover field {name!r} contains label or table-border residue",
                    }
                )

    for name in _CHECKBOX_TAGS:
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

    observations = _field_observations(root)
    field_values = {
        field: [
            value for element in _elements(root, names) if (value := _text(element))
        ]
        for field, names in _FIELD_TAGS.items()
    }
    value_frequencies = {
        name: [_text(element) for element in _elements(root, (name,)) if _text(element)]
        for name in _CATEGORICAL_TAGS
    }
    unparsed_sections = []
    for element in _elements(root, ("unparsedSection",)):
        value = _text(element)
        is_boilerplate = bool(STATUTORY_PAGE_ARTIFACT_RE.search(value))
        unparsed_sections.append(
            {
                "accession": accession,
                "table_index": element.attrib.get("tableIndex", ""),
                "role": element.attrib.get("role", ""),
                "char_length": len(value),
                "snippet": " ".join(value.split())[:240],
                "is_boilerplate": is_boilerplate,
            }
        )

    return {
        "accession": accession,
        "form": "13D",
        "family": "13D",
        "error": None,
        "field_observations": observations,
        "field_values": field_values,
        "anomalies": anomalies,
        "review_signals": [],
        "value_frequencies": value_frequencies,
        "unparsed_sections": unparsed_sections,
    }


def _empty_observations() -> dict[str, dict[str, int]]:
    return {
        field: {"occurrences": 0, "populated_occurrences": 0, "blank_occurrences": 0}
        for field in _FIELD_TAGS
    }


def analyze_case(case_dir: Path, record: dict[str, Any]) -> dict[str, Any] | None:
    xml_path = case_dir / "operations" / "render_to_xml.xml"
    if (
        not xml_path.is_file()
        and not (case_dir / "operations" / "render_to_txt.txt").is_file()
    ):
        return None
    accession = str(record.get("accession", case_dir.name))
    if not xml_path.is_file():
        return {
            "accession": accession,
            "form": "13D",
            "family": "13D",
            "error": "missing_rendered_xml",
            "field_observations": _empty_observations(),
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
        }
    try:
        xml_text = xml_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return {
            "accession": accession,
            "form": "13D",
            "family": "13D",
            "error": "unreadable_xml",
            "field_observations": _empty_observations(),
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
        }
    return _analyze_xml(xml_text, accession)


def summarize_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    case_count = len(case_reports)
    observations: dict[str, Counter[str]] = {field: Counter() for field in _FIELD_TAGS}
    anomalies: list[dict[str, Any]] = []
    anomaly_counts: Counter[str] = Counter()
    unparsed_sections: list[dict[str, Any]] = []
    boilerplate_unparsed_count = 0
    value_counts: dict[str, Counter[str]] = {
        name: Counter() for name in _CATEGORICAL_TAGS
    }
    value_cases: dict[str, dict[str, set[str]]] = {
        name: {} for name in _CATEGORICAL_TAGS
    }

    for report in case_reports:
        accession = str(report.get("accession", ""))
        for field, fields in report.get("field_observations", {}).items():
            for key in ("occurrences", "populated_occurrences", "blank_occurrences"):
                observations.setdefault(field, Counter())[key] += fields.get(key, 0)
            if fields.get("populated_occurrences", 0):
                observations[field]["cases_with_value"] += 1
        for anomaly in report.get("anomalies", []):
            anomaly_counts[anomaly["kind"]] += 1
            anomalies.append(anomaly)
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

    return {
        "family": "13D",
        "case_count": case_count,
        "field_scorecard": field_scorecard,
        "anomalies": anomalies,
        "anomaly_count": len(anomalies),
        "anomaly_summary": {
            "kind_counts": dict(sorted(anomaly_counts.items())),
            "sample_anomalies": anomalies[:10],
        },
        "review_signals": [],
        "review_signal_count": 0,
        "unparsed_section_count": len(unparsed_sections),
        "boilerplate_unparsed_count": boilerplate_unparsed_count,
        "substantive_unparsed_count": len(substantive_unparsed),
        "unparsed_samples": unparsed_samples,
        "value_frequencies": value_summary,
    }


__all__ = ["analyze_case", "summarize_cases"]
