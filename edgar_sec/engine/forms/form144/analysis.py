"""Semantic review analysis and diagnostics for SEC Form 144 filings."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.form144.taxonomy import (
    FORM144_LIVE_TEST_TYPES,
    FORM144_SUBMISSION_TYPES,
)
from edgar_sec.engine.forms.common.extraction import local_name, validate_xml_schema
from edgar_sec.engine.forms.form144.field_specs import FORM144_FIELD_SPECS
from edgar_sec.engine.forms.common.statutory import HEADER_LEAK_RE
from edgar_sec.engine.forms.common.unparsed import load_unparsed_sections
from edgar_sec.engine.document.html.tree import parse_html
from edgar_sec.foundation.regex.builder import build_alternation

_CORE_FIELDS = (
    "issuerName",
    "nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold",
    "securitiesClassTitle",
    "noOfUnitsSold",
    "aggregateMarketValue",
    "approxSaleDate",
    "signature",
)

_BOILERPLATE_TERMS = (
    "sec 1147",
    "instruction",
    "omb number",
    "18 u.s.c.",
    "potential persons",
    "transmit for filing",
)
_UNDERSCORE_FILL_RE = re.compile(r"_{2,}")
_HYPHEN_FILL_RE = re.compile(r"-{3,}")
_ZIP_5DIGIT_RE = re.compile(r"^\d{5}$")
_AREA_CODE_3DIGIT_RE = re.compile(r"^\d{3}$")
_YEAR_4DIGIT_RE = re.compile(r"^\d{4}$")
_BOILERPLATE_LEAK_ALT = build_alternation(
    (
        "address of issuer",
        "name of issuer",
        "sec use only",
        "instructions",
        "document sequence",
        "file number",
        "area code number",
    )
)
_BOILERPLATE_LEAK_RE = re.compile(rf"(?:{_BOILERPLATE_LEAK_ALT})", re.I)


def _children(parent: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in parent if local_name(child.tag) == name]


def _has_text(parent: ET.Element, name: str) -> bool:
    return any((child.text or "").strip() for child in _children(parent, name))


def analyze_case(case_dir: Path, record: dict[str, Any]) -> dict[str, Any] | None:
    """Analyze a single review case directory producing Form 144 diagnostics."""
    accession = str(record.get("accession", ""))
    xml_path = case_dir / "operations" / "render_to_xml.xml"
    if not xml_path.is_file():
        return None

    try:
        root = ET.fromstring(xml_path.read_bytes())
    except ET.ParseError:
        return {
            "accession": accession,
            "error": "malformed_xml",
            "core_fields": {f: False for f in _CORE_FIELDS},
            "anomalies": [
                {
                    "accession": accession,
                    "kind": "malformed_xml",
                    "detail": "XML parse failed",
                }
            ],
            "review_signals": [],
            "value_frequencies": {},
            "unparsed_section_count": 0,
        }

    tag_values: dict[str, list[str]] = {}
    for elem in root.iter():
        clean = local_name(elem.tag)
        if elem.text and elem.text.strip():
            tag_values.setdefault(clean, []).append(elem.text.strip())

    core_presence: dict[str, bool] = {
        field: bool(tag_values.get(field)) for field in _CORE_FIELDS
    }

    anomalies: list[dict[str, Any]] = []
    review_signals: list[dict[str, Any]] = []

    anomalies.extend(validate_xml_schema(root, FORM144_FIELD_SPECS, accession))

    header = next(
        (node for node in root.iter() if local_name(node.tag) == "headerData"), None
    )
    form_data = next(
        (node for node in root.iter() if local_name(node.tag) == "formData"), None
    )

    def require(parent: ET.Element | None, name: str, path: str) -> None:
        if parent is None or not _has_text(parent, name):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": f"missing_schema_{path}",
                    "detail": f"Required schema value {path} is missing",
                }
            )

    require(header, "submissionType", "submissionType")
    filer_info = (
        next(
            (node for node in header.iter() if local_name(node.tag) == "filerInfo"),
            None,
        )
        if header is not None
        else None
    )
    if filer_info is not None:
        require(filer_info, "liveTestFlag", "liveTestFlag")
        if not _children(filer_info, "flags"):
            require(filer_info, "flags", "flags")
        for field in ("cik", "ccc"):
            parent = (
                next(
                    (
                        node
                        for node in header.iter()
                        if local_name(node.tag) == "filerCredentials"
                    ),
                    None,
                )
                if header is not None
                else None
            )
            require(parent, field, field)
        contact = (
            next(
                (node for node in header.iter() if local_name(node.tag) == "contact"),
                None,
            )
            if header is not None
            else None
        )
        for field in ("contactName", "contactPhone", "contactEmail"):
            require(contact, field, field)

    submission_type = next(iter(tag_values.get("submissionType", [])), "")
    if submission_type == "144/A":
        require(header, "previousAccessionNumber", "previousAccessionNumber")
    elif submission_type and submission_type not in FORM144_SUBMISSION_TYPES:
        anomalies.append(
            {
                "accession": accession,
                "kind": "invalid_submissionType",
                "detail": f"Unsupported Form 144 submission type: {submission_type}",
            }
        )
    live_test = next(iter(tag_values.get("liveTestFlag", [])), "")
    if live_test and live_test not in FORM144_LIVE_TEST_TYPES:
        anomalies.append(
            {
                "accession": accession,
                "kind": "invalid_liveTestFlag",
                "detail": f"Unsupported Form 144 live/test flag: {live_test}",
            }
        )

    issuer = (
        next((node for node in form_data if local_name(node.tag) == "issuerInfo"), None)
        if form_data is not None
        else None
    )
    issuer_fields = [
        "issuerName",
        "issuerContactPhone",
        "nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold",
    ]
    if filer_info is not None:
        issuer_fields.append("issuerCik")
    for field in issuer_fields:
        require(issuer, field, field)
    issuer_address = (
        next((node for node in issuer if local_name(node.tag) == "issuerAddress"), None)
        if issuer is not None
        else None
    )
    for field in ("street1", "city", "stateOrCountry", "zipCode"):
        require(issuer_address, field, f"issuerAddress.{field}")
    relationships = (
        next(
            (
                node
                for node in issuer
                if local_name(node.tag) == "relationshipsToIssuer"
            ),
            None,
        )
        if issuer is not None
        else None
    )
    if relationships is None or not _children(relationships, "relationshipToIssuer"):
        require(relationships, "relationshipToIssuer", "relationshipToIssuer")
    information = (
        _children(form_data, "securitiesInformation") if form_data is not None else []
    )
    if not information:
        require(form_data, "securitiesInformation", "securitiesInformation")
    if form_data is not None and not _children(form_data, "securitiesToBeSold"):
        require(form_data, "securitiesToBeSold", "securitiesToBeSold")
    for index, item in enumerate(information):
        for field in (
            "securitiesClassTitle",
            "noOfUnitsSold",
            "aggregateMarketValue",
            "noOfUnitsOutstanding",
            "approxSaleDate",
            "securitiesExchangeName",
        ):
            require(item, field, f"securitiesInformation[{index}].{field}")
        broker = next(
            (
                node
                for node in item
                if local_name(node.tag) == "brokerOrMarketmakerDetails"
            ),
            None,
        )
        require(broker, "name", f"securitiesInformation[{index}].broker.name")
        address = (
            next((node for node in broker if local_name(node.tag) == "address"), None)
            if broker is not None
            else None
        )
        for field in ("street1", "city", "stateOrCountry", "zipCode"):
            require(
                address, field, f"securitiesInformation[{index}].broker.address.{field}"
            )

    flag = next(
        iter(tag_values.get("nothingToReportFlagOnSecuritiesSoldInPast3Months", [])),
        "",
    )
    require(
        form_data,
        "nothingToReportFlagOnSecuritiesSoldInPast3Months",
        "nothingToReportFlagOnSecuritiesSoldInPast3Months",
    )
    if (
        flag == "N"
        and form_data is not None
        and not _children(form_data, "securitiesSoldInPast3Months")
    ):
        require(form_data, "securitiesSoldInPast3Months", "securitiesSoldInPast3Months")
    if (
        flag == "Y"
        and form_data is not None
        and _children(form_data, "securitiesSoldInPast3Months")
    ):
        anomalies.append(
            {
                "accession": accession,
                "kind": "conflicting_nothingToReportFlag",
                "detail": "No-report flag Y conflicts with reported securities sales",
            }
        )
    if form_data is not None:
        for index, item in enumerate(_children(form_data, "securitiesToBeSold")):
            for field in (
                "securitiesClassTitle",
                "acquiredDate",
                "natureOfAcquisitionTransaction",
                "isGiftTransaction",
                "amountOfSecuritiesAcquired",
                "natureOfPayment",
            ):
                require(item, field, f"securitiesToBeSold[{index}].{field}")
        for index, item in enumerate(
            _children(form_data, "securitiesSoldInPast3Months")
        ):
            seller = next(
                (node for node in item if local_name(node.tag) == "sellerDetails"),
                None,
            )
            require(seller, "name", f"securitiesSoldInPast3Months[{index}].seller.name")
            address = (
                next(
                    (node for node in seller if local_name(node.tag) == "address"), None
                )
                if seller is not None
                else None
            )
            for field in ("street1", "city", "stateOrCountry", "zipCode"):
                require(
                    address,
                    field,
                    f"securitiesSoldInPast3Months[{index}].seller.address.{field}",
                )
            for field in (
                "securitiesClassTitle",
                "saleDate",
                "amountOfSecuritiesSold",
                "grossProceeds",
            ):
                require(item, field, f"securitiesSoldInPast3Months[{index}].{field}")

    signature = (
        next(
            (node for node in form_data if local_name(node.tag) == "noticeSignature"),
            None,
        )
        if form_data is not None
        else None
    )
    require(signature, "noticeDate", "noticeDate")
    require(signature, "signature", "signature")

    for req in (
        "issuerName",
        "nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold",
        "noOfUnitsSold",
        "signature",
    ):
        if not core_presence.get(req):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": f"missing_{req}",
                    "detail": f"Required field {req!r} is missing",
                }
            )

    for name_field in (
        "issuerName",
        "nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold",
    ):
        for val in tag_values.get(name_field, []):
            lower_val = val.lower()
            if any(
                term in lower_val for term in _BOILERPLATE_TERMS
            ) or HEADER_LEAK_RE.search(val):
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": "boilerplate_leak",
                        "detail": f"Boilerplate text leaked into {name_field}: {val[:50]!r}",
                    }
                )

    for field_name in (
        "issuerName",
        "nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold",
        "securitiesClassTitle",
        "signature",
    ):
        for val in tag_values.get(field_name, []):
            if _UNDERSCORE_FILL_RE.search(val) or _HYPHEN_FILL_RE.search(val):
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": "symbol_fill_leak",
                        "detail": f"Fill characters leaked into {field_name}: {val[:50]!r}",
                    }
                )

    for qty_field in ("noOfUnitsSold", "noOfUnitsOutstanding"):
        for val in tag_values.get(qty_field, []):
            if _ZIP_5DIGIT_RE.fullmatch(val) and int(val) % 100 != 0:
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": "zip_code_in_units",
                        "detail": f"Suspected ZIP code {val} leaked into {qty_field}",
                    }
                )
            elif _YEAR_4DIGIT_RE.fullmatch(val) and 1990 <= int(val) <= 2025:
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": "year_in_units_or_value",
                        "detail": f"Suspected calendar year {val} leaked into {qty_field}",
                    }
                )

    for val in tag_values.get("aggregateMarketValue", []):
        if _AREA_CODE_3DIGIT_RE.fullmatch(val):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "area_code_in_market_value",
                    "detail": f"Suspected telephone area code {val} in aggregateMarketValue",
                }
            )
        elif _YEAR_4DIGIT_RE.fullmatch(val) and 1990 <= int(val) <= 2025:
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "year_in_units_or_value",
                    "detail": f"Suspected calendar year {val} in aggregateMarketValue",
                }
            )

    for title_field in ("securitiesClassTitle", "issuerName", "name"):
        for val in tag_values.get(title_field, []):
            if _BOILERPLATE_LEAK_RE.search(val):
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": "boilerplate_field_leak",
                        "detail": f"Boilerplate prompt leaked into {title_field}: {val[:50]!r}",
                    }
                )

    if tag_values.get("planAdoptionDate"):
        for pd in tag_values["planAdoptionDate"]:
            review_signals.append(
                {
                    "accession": accession,
                    "kind": "10b5_1_plan",
                    "value": pd,
                }
            )

    for gift_flag in tag_values.get("isGiftTransaction", []):
        if gift_flag.upper() == "Y":
            review_signals.append(
                {
                    "accession": accession,
                    "kind": "gift_transaction",
                    "value": "Table I gift transaction reported",
                }
            )

    exchanges = tag_values.get("securitiesExchangeName", [])
    relationships = tag_values.get("relationshipToIssuer", [])

    unparsed_sections: list[dict[str, Any]] = []
    for record_section in load_unparsed_sections(case_dir, root):
        t_idx = record_section.get("table_index", "")
        role = str(record_section.get("role", ""))
        content = str(record_section.get("content", ""))
        text = (
            parse_html(content).text()
            if record_section.get("content_type") == "text/html"
            else content
        ).strip()
        snippet = " ".join(text.split())[:240].strip()
        lower_snip = snippet.lower()
        is_boilerplate = any(term in lower_snip for term in _BOILERPLATE_TERMS)
        unparsed_sections.append(
            {
                "accession": accession,
                "table_index": t_idx,
                "role": role,
                "char_length": len(text),
                "snippet": snippet,
                "is_boilerplate": is_boilerplate,
            }
        )

    return {
        "accession": accession,
        "error": None,
        "core_fields": core_presence,
        "anomalies": anomalies,
        "review_signals": review_signals,
        "value_frequencies": {
            "exchange": exchanges,
            "relationship": relationships,
        },
        "unparsed_section_count": len(unparsed_sections),
        "unparsed_sections": unparsed_sections,
    }


def summarize_cases(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate Form 144 case analyses into an overall summary report."""
    case_count = max(1, len(case_reports))
    field_counts: Counter[str] = Counter()
    all_anomalies: list[dict[str, Any]] = []
    all_signals: list[dict[str, Any]] = []
    all_unparsed: list[dict[str, Any]] = []
    exchange_freq: Counter[str] = Counter()
    relationship_freq: Counter[str] = Counter()

    for rep in case_reports:
        for f, present in rep.get("core_fields", {}).items():
            if present:
                field_counts[f] += 1
        all_anomalies.extend(rep.get("anomalies", []))
        all_signals.extend(rep.get("review_signals", []))
        all_unparsed.extend(rep.get("unparsed_sections", []))

        vf = rep.get("value_frequencies", {})
        for ex in vf.get("exchange", []):
            exchange_freq[ex.upper()] += 1
        for rel in vf.get("relationship", []):
            relationship_freq[rel] += 1

    substantive_unparsed = [
        item for item in all_unparsed if not item.get("is_boilerplate")
    ]
    boilerplate_unparsed_count = len(all_unparsed) - len(substantive_unparsed)

    unparsed_samples: list[dict[str, Any]] = []
    target_pool = substantive_unparsed if substantive_unparsed else all_unparsed
    for item in target_pool:
        if not any(s["snippet"] == item["snippet"] for s in unparsed_samples):
            unparsed_samples.append(item)
            if len(unparsed_samples) >= 10:
                break

    field_scorecard = {
        field: {
            "cases_with_value": field_counts[field],
            "cases_without_value": case_count - field_counts[field],
            "case_missing_percent": round(
                (case_count - field_counts[field]) * 100 / case_count, 2
            ),
        }
        for field in _CORE_FIELDS
    }

    return {
        "family": "144",
        "case_count": case_count,
        "field_scorecard": field_scorecard,
        "anomalies": all_anomalies,
        "anomaly_count": len(all_anomalies),
        "review_signals": all_signals,
        "review_signal_count": len(all_signals),
        "unparsed_section_count": len(all_unparsed),
        "boilerplate_unparsed_count": boilerplate_unparsed_count,
        "substantive_unparsed_count": len(substantive_unparsed),
        "unparsed_samples": unparsed_samples,
        "value_frequencies": {
            "exchange": {
                "distinct_values": len(exchange_freq),
                "top_values": [
                    {"value": val, "count": count}
                    for val, count in exchange_freq.most_common(10)
                ],
            },
            "relationship": {
                "distinct_values": len(relationship_freq),
                "top_values": [
                    {"value": val, "count": count}
                    for val, count in relationship_freq.most_common(10)
                ],
            },
        },
    }


__all__ = [
    "analyze_case",
    "summarize_cases",
]
