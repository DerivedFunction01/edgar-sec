"""XML audit and validation rules for ownership documents."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

from edgar_sec.engine.forms.common.phrases.statutory import (
    HEADER_LEAK_RE,
    STATUTORY_PAGE_ARTIFACT_RE,
)
from edgar_sec.engine.forms.common.signatures.patterns import SIG_BOILERPLATE_TERMS
from edgar_sec.engine.forms.common.values.dates import parse_schema_date, reported_year
from edgar_sec.engine.forms.common.xml.unparsed import load_unparsed_sections
from edgar_sec.engine.forms.ownership.analysis.fields import (
    FIELD_PATHS,
    FIELD_VALUE_TAGS,
    REQUIRED_DOCUMENT_FIELDS,
    UNAVAILABLE_DOCUMENT_FIELDS,
)
from edgar_sec.engine.forms.ownership.patterns import is_ownership_boilerplate
from edgar_sec.engine.forms.ownership.specs.schema import ownership_schema_anomalies
from edgar_sec.foundation.text.date_patterns import NUMERIC_DATE_RE
from edgar_sec.foundation.text.patterns import RE_WHITESPACE


def _field_observations(root: ET.Element) -> dict[str, dict[str, int]]:
    observations: dict[str, dict[str, int]] = {}
    for field, paths in FIELD_PATHS.items():
        elements = [element for path in paths for element in root.findall(path)]
        populated = sum(bool(_element_text(element)) for element in elements)
        observations[field] = {
            "occurrences": len(elements),
            "populated_occurrences": populated,
            "blank_occurrences": len(elements) - populated,
        }
    return observations


def _field_values(root: ET.Element) -> dict[str, list[str]]:
    return {
        field: [
            text
            for element in root.iter(tag)
            if (
                text := _element_text(
                    element.find("value")
                    if element.find("value") is not None
                    else element
                )
            )
        ]
        for field, tag in FIELD_VALUE_TAGS.items()
    }


def _element_text(elem: ET.Element | None) -> str:
    if elem is None or elem.text is None:
        return ""
    return elem.text.strip()


def analyze_ownership_xml(
    xml_bytes: bytes,
    accession: str = "",
    *,
    unparsed_sections: tuple[dict[str, object], ...] | None = None,
    case_dir: Path | None = None,
) -> dict[str, Any]:
    """Inspect ownership XML fields, schema anomalies, and unparsed sections."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as err:
        return {
            "accession": accession,
            "error": f"xml_parse_error: {err}",
            "element_counts": {},
            "anomalies": [{"kind": "xml_parse_error", "detail": str(err)}],
            "unparsed_sections": [],
            "core_fields": {},
        }

    element_counts: Counter[str] = Counter()
    anomalies: list[dict[str, Any]] = ownership_schema_anomalies(root, accession)
    review_signals: list[dict[str, Any]] = []
    source_sections = (
        unparsed_sections
        if unparsed_sections is not None
        else load_unparsed_sections(case_dir or Path("/__ownership_no_case__"), root)
    )
    analyzed_sections: list[dict[str, Any]] = []
    period_text = _element_text(root.find("periodOfReport"))
    reference_year = reported_year((period_text,))

    for elem in root.iter():
        element_counts[elem.tag] += 1

    if root.tag != "ownershipDocument":
        anomalies.append(
            {
                "accession": accession,
                "kind": "invalid_document_envelope",
                "value": root.tag,
                "detail": "root element is not ownershipDocument",
            }
        )

    # Invariant: underlyingSecurityTitle should not contain dates or column headers
    for u_elem in root.iter("underlyingSecurityTitle"):
        val_elem = u_elem.find("value")
        text = _element_text(val_elem if val_elem is not None else u_elem)
        lower = text.lower()
        if text and (NUMERIC_DATE_RE.search(text) or "|" in text):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "date_in_underlying_security_title",
                    "value": text,
                    "detail": "underlying security title contains date pattern",
                }
            )
        if text and HEADER_LEAK_RE.search(text):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "header_leak_in_underlying_security_title",
                    "value": text,
                    "detail": "underlying security title contains column header text",
                }
            )

    # Invariant: securityTitle should not contain instruction boilerplate or column headers
    for s_elem in root.iter("securityTitle"):
        val_elem = s_elem.find("value")
        text = _element_text(val_elem if val_elem is not None else s_elem)
        lower = text.lower()
        if text and ("title of" in lower or "instr." in lower):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "boilerplate_in_security_title",
                    "value": text,
                    "detail": "security title contains instruction header text",
                }
            )
        if text and HEADER_LEAK_RE.search(text):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "header_leak_in_security_title",
                    "value": text,
                    "detail": "security title contains column header text",
                }
            )

    # Invariant: signatureName should not contain statutory boilerplate
    for sig_name_elem in root.iter("signatureName"):
        text = _element_text(sig_name_elem)
        lower = text.lower()
        if text and any(b in lower for b in SIG_BOILERPLATE_TERMS):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "boilerplate_in_signature_name",
                    "value": text,
                    "detail": "signature name contains statutory boilerplate text",
                }
            )

    # Invariant: rptOwnerName and issuerName should not contain statutory boilerplate
    for owner_elem in root.iter("rptOwnerName"):
        text = _element_text(owner_elem)
        lower = text.lower()
        if text and (
            any(
                phrase in lower
                for phrase in (
                    "filed pursuant to",
                    "section 16(a)",
                    "holding company act",
                    "investment company act",
                    "(first)",
                    "(middle)",
                    "check this box",
                )
            )
            or HEADER_LEAK_RE.search(text)
            or STATUTORY_PAGE_ARTIFACT_RE.search(text)
        ):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "boilerplate_in_rpt_owner_name",
                    "value": text,
                    "detail": "reporting owner name contains statutory or template boilerplate",
                }
            )

    # Invariant: dates must match numeric date structure
    for date_tag in (
        "periodOfReport",
        "dateOfOriginalSubmission",
        "transactionDate",
        "exerciseDate",
        "expirationDate",
    ):
        for d_elem in root.iter(date_tag):
            val_elem = d_elem.find("value")
            text = _element_text(val_elem if val_elem is not None else d_elem)
            parsed_date = parse_schema_date(text, reference_year) if text else None
            if text and (parsed_date is None or text != parsed_date.iso):
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": f"invalid_{date_tag}",
                        "value": text,
                        "detail": f"{date_tag} does not contain recognized date",
                    }
                )

    for date_tag in ("signatureDate",):
        for d_elem in root.iter(date_tag):
            text = _element_text(d_elem)
            parsed_date = parse_schema_date(text, reference_year) if text else None
            if text and (parsed_date is None or text != parsed_date.iso):
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": f"invalid_{date_tag}",
                        "value": text,
                        "detail": f"{date_tag} is not a valid recognized date",
                    }
                )

    for date_tag in ("securityTitle",):
        for s_elem in root.iter(date_tag):
            val_elem = s_elem.find("value")
            text = _element_text(val_elem if val_elem is not None else s_elem)
            if text and NUMERIC_DATE_RE.search(text):
                finding = {
                    "accession": accession,
                    "kind": "date_in_security_title",
                    "value": text,
                    "detail": "security title contains a complete date pattern",
                }
                if "option" in text.lower():
                    review_signals.append(
                        {
                            **finding,
                            "kind": "date_in_option_security_title",
                            "detail": "date appears in a descriptive option title; source text preserved",
                        }
                    )
                else:
                    anomalies.append(finding)

    for code_elem in root.iter("transactionCode"):
        code = _element_text(code_elem)
        if code and HEADER_LEAK_RE.search(code):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "header_leak_in_transaction_code",
                    "value": code,
                    "detail": "transaction code contains column header text",
                }
            )

    # Invariant: directOrIndirectOwnership must be D or I
    for own_elem in root.iter("directOrIndirectOwnership"):
        val_elem = own_elem.find("value")
        text = _element_text(val_elem if val_elem is not None else own_elem)
        if text and text.upper() not in ("D", "I"):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "invalid_ownership_nature",
                    "value": text,
                    "detail": f"ownership form '{text}' is neither 'D' nor 'I'",
                }
            )

    # Check presence of canonical core fields
    core_fields: dict[str, bool] = {
        "periodOfReport": bool(_element_text(root.find("periodOfReport"))),
        "issuerCik": bool(_element_text(root.find("issuer/issuerCik"))),
        "issuerName": bool(_element_text(root.find("issuer/issuerName"))),
        "issuerTradingSymbol": bool(
            _element_text(root.find("issuer/issuerTradingSymbol"))
        ),
        "rptOwnerName": bool(
            _element_text(root.find("reportingOwner/reportingOwnerId/rptOwnerName"))
        ),
        "rptOwnerCik": bool(
            _element_text(root.find("reportingOwner/reportingOwnerId/rptOwnerCik"))
        ),
        "signatureName": bool(_element_text(root.find("ownerSignature/signatureName"))),
        "signatureDate": bool(_element_text(root.find("ownerSignature/signatureDate"))),
    }
    field_observations = _field_observations(root)
    missing_required_fields = [
        field for field in REQUIRED_DOCUMENT_FIELDS if not core_fields.get(field)
    ]
    if missing_required_fields:
        anomalies.append(
            {
                "accession": accession,
                "kind": "missing_required_fields",
                "value": ", ".join(missing_required_fields),
                "detail": "required ownership document fields are missing or blank",
            }
        )
    unavailable_fields = [
        field for field in UNAVAILABLE_DOCUMENT_FIELDS if not core_fields.get(field)
    ]
    if unavailable_fields:
        anomalies.append(
            {
                "accession": accession,
                "kind": "fields_absent_from_document_body",
                "value": ", ".join(unavailable_fields),
                "detail": (
                    "these fields come from the EDGAR submission header, "
                    "not the ownership document body"
                ),
            }
        )

    for unparsed in source_sections:
        text = str(unparsed.get("content", ""))
        snippet = RE_WHITESPACE.sub(" ", text)[:240].strip()
        lower_snip = snippet.lower()
        is_boilerplate = bool(
            STATUTORY_PAGE_ARTIFACT_RE.search(lower_snip)
            or is_ownership_boilerplate(lower_snip)
        )
        analyzed_sections.append(
            {
                "accession": accession,
                "table_index": str(unparsed.get("table_index", "")),
                "role": str(unparsed.get("role", "")),
                "char_length": len(text),
                "snippet": snippet,
                "is_boilerplate": is_boilerplate,
            }
        )

    field_values = _field_values(root)

    return {
        "accession": accession,
        "element_counts": dict(sorted(element_counts.items())),
        "anomalies": anomalies,
        "review_signals": review_signals,
        "unparsed_sections": analyzed_sections,
        "core_fields": core_fields,
        "field_observations": field_observations,
        "missing_required_fields": missing_required_fields,
        "field_values": field_values,
    }
