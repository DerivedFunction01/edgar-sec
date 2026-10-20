from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from edgar_sec.domain.forms.families.beneficial_ownership.taxonomy import (
    SCHEDULE_13D_FUND_TYPES,
    SCHEDULE_13D_MEMBER_TYPES,
    SCHEDULE_13D_REPORTING_PERSON_TYPES,
    SCHEDULE_13D_SUBMISSION_TYPES,
    SCHEDULE_13G_BUSINESS_ENGAGED_TYPES,
    SCHEDULE_13G_GROUP_TYPES,
    SCHEDULE_13G_REPORTING_PERSON_TYPES,
    SCHEDULE_13G_RULE_TYPES,
    SCHEDULE_13G_SUBMISSION_TYPES,
)
from edgar_sec.domain.taxonomy.jurisdictions import EDGAR_JURISDICTION_CODES
from edgar_sec.engine.forms.common.extraction import (
    FieldKind,
    FieldSpec,
    RequiredElement,
    local_name,
    validate_xml_required,
    validate_xml_values,
)


def _elements(root: ET.Element, names: tuple[str, ...]) -> list[ET.Element]:
    name_set = set(names)
    return [element for element in root.iter() if local_name(element.tag) in name_set]


def _text(element: ET.Element) -> str:
    return "".join(element.itertext()).strip()


def analyze_schema_xml(
    root: ET.Element, accession: str, family: str
) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    required_nodes = (
        (
            "coverPageHeader",
            "coverPageHeaderReportingPersonDetails",
            "items",
            "signatureInformation",
        )
        if family == "13G"
        else ("coverPageHeader", "reportingPersons", "items1To7", "signatureInfo")
    )
    anomalies.extend(
        validate_xml_required(
            root,
            tuple(
                RequiredElement(
                    parent="formData",
                    name=name,
                    field=name,
                    require_text=False,
                )
                for name in required_nodes
            ),
            accession,
        )
    )

    choices = {
        "submissionType": (
            SCHEDULE_13G_SUBMISSION_TYPES
            if family == "13G"
            else SCHEDULE_13D_SUBMISSION_TYPES
        ),
        "typeOfReportingPerson": (
            SCHEDULE_13G_REPORTING_PERSON_TYPES
            if family == "13G"
            else SCHEDULE_13D_REPORTING_PERSON_TYPES
        ),
    }
    choices.update(
        {
            "memberGroup": SCHEDULE_13G_GROUP_TYPES,
            "designateRulePursuantThisScheduleFiled": SCHEDULE_13G_RULE_TYPES,
            "typeOfPersonFiling": SCHEDULE_13G_BUSINESS_ENGAGED_TYPES,
            "citizenshipOrOrganization": EDGAR_JURISDICTION_CODES,
        }
        if family == "13G"
        else {
            "memberOfGroup": SCHEDULE_13D_MEMBER_TYPES,
            "fundType": SCHEDULE_13D_FUND_TYPES,
        }
    )
    anomalies.extend(
        validate_xml_values(
            root,
            tuple(
                FieldSpec(
                    tag,
                    FieldKind.ENUM,
                    allowed_values=allowed,
                    anomaly_kind="invalid_schema_code",
                    detail="value is not present in the supplied XML choice list",
                )
                for tag, allowed in choices.items()
            ),
            accession,
        )
    )

    event_tag = (
        "eventDateRequiresFilingThisStatement" if family == "13G" else "dateOfEvent"
    )
    for cover in _elements(root, ("coverPageHeader",)):
        dates = _elements(cover, (event_tag,))
        if not dates:
            anomalies.append(_missing_field(accession, event_tag))
        anomalies.extend(
            validate_xml_values(
                cover,
                (
                    FieldSpec(
                        event_tag,
                        FieldKind.DATE,
                        date_lexeme="MDY",
                        anomaly_kind="invalid_schema_date",
                        detail="date must be a real calendar date in MM-DD-YYYY form",
                    ),
                ),
                accession,
            )
        )

    for details in _elements(root, ("signatureDetails",)):
        anomalies.extend(
            validate_xml_required(
                details,
                tuple(
                    RequiredElement(
                        parent="",
                        name=required,
                        field=f"signatureDetails.{required}",
                    )
                    for required in ("signature", "title", "date")
                ),
                accession,
            )
        )
        anomalies.extend(
            validate_xml_values(
                details,
                (
                    FieldSpec(
                        "signatureDetails.date",
                        FieldKind.DATE,
                        date_lexeme="MDY",
                        anomaly_kind="invalid_schema_date",
                        detail="date must be a real calendar date in MM-DD-YYYY form",
                    ),
                ),
                accession,
            )
        )
    return anomalies


def _missing_field(accession: str, field: str) -> dict[str, str]:
    return {
        "accession": accession,
        "kind": "missing_required_schema_field",
        "field": field,
        "detail": "the supplied XML mapping requires this field",
    }


__all__ = ["analyze_schema_xml"]
