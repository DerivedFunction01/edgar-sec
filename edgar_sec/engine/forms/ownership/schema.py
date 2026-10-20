from __future__ import annotations

import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.ownership.taxonomy import (
    OWNERSHIP_HOLDING_FORM_TYPES,
    OWNERSHIP_TRANSACTION_FORM_TYPES,
)
from edgar_sec.engine.forms.common.extraction import validate_xml_schema
from edgar_sec.engine.forms.ownership.field_specs import OWNERSHIP_SCHEMA_FIELDS


def _field_value(element: ET.Element | None) -> str:
    if element is None:
        return ""
    value = element.find("value")
    return ((value.text if value is not None else element.text) or "").strip()


def _add_condition(
    anomalies: list[dict[str, str]],
    accession: str,
    kind: str,
    detail: str,
) -> None:
    anomalies.append({"accession": accession, "kind": kind, "detail": detail})


def _exactly_one_value(
    parent: ET.Element,
    field_names: tuple[str, str],
    anomalies: list[dict[str, str]],
    accession: str,
    condition: str,
) -> None:
    populated = sum(bool(_field_value(parent.find(name))) for name in field_names)
    if populated != 1:
        _add_condition(
            anomalies,
            accession,
            f"invalid_{condition}_values",
            f"exactly one of {field_names[0]} or {field_names[1]} must have a value",
        )


def ownership_schema_anomalies(
    root: ET.Element, accession: str
) -> list[dict[str, str]]:
    anomalies: list[dict[str, str]] = []
    anomalies.extend(validate_xml_schema(root, OWNERSHIP_SCHEMA_FIELDS, accession))
    document_type = (root.findtext("documentType") or "").strip()
    original_date = root.find("dateOfOriginalSubmission")
    if document_type.endswith("/A") and not _field_value(original_date):
        _add_condition(
            anomalies,
            accession,
            "missing_date_of_original_submission",
            "dateOfOriginalSubmission is required for an ownership amendment",
        )
    elif (
        document_type and not document_type.endswith("/A") and original_date is not None
    ):
        _add_condition(
            anomalies,
            accession,
            "date_of_original_submission_not_applicable",
            "dateOfOriginalSubmission applies only to ownership amendments",
        )

    for tag in ("schemaVersion", "issuerIrsNumber"):
        if root.find(f".//{tag}") is not None:
            anomalies.append(
                {
                    "accession": accession,
                    "kind": f"not_applicable_{tag}",
                    "value": (root.findtext(f".//{tag}") or "").strip(),
                    "detail": f"{tag} is not part of the ownership primary-document schema",
                }
            )

    for transaction in root.iter():
        if transaction.tag not in {
            "nonDerivativeTransaction",
            "derivativeTransaction",
            "nonDerivativeHolding",
            "derivativeHolding",
        }:
            continue
        coding = transaction.find("transactionCoding")
        if coding is None:
            continue
        form_type = (coding.findtext("transactionFormType") or "").strip()
        if not form_type:
            continue
        if transaction.tag.endswith("Holding"):
            valid = form_type in OWNERSHIP_HOLDING_FORM_TYPES and document_type in {
                "5",
                "5/A",
            }
        else:
            valid = form_type in OWNERSHIP_TRANSACTION_FORM_TYPES
        if not valid:
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "invalid_transactionFormType",
                    "value": form_type,
                    "detail": "transactionFormType does not match the ownership row type",
                }
            )

    for relationship in root.iter("reportingOwnerRelationship"):
        role_fields = tuple(
            relationship.find(name)
            for name in ("isDirector", "isOfficer", "isTenPercentOwner", "isOther")
        )
        role_values = tuple(
            (field.text or "").strip().lower() if field is not None else ""
            for field in role_fields
        )
        if not any(value in {"true", "1"} for value in role_values):
            _add_condition(
                anomalies,
                accession,
                "relationship_no_true_role",
                "at least one reporting owner relationship flag must be true",
            )
        if role_values[1] in {"true", "1"}:
            if not _field_value(relationship.find("officerTitle")):
                _add_condition(
                    anomalies,
                    accession,
                    "missing_officer_title",
                    "officerTitle is required when isOfficer is true",
                )
        if role_values[3] in {"true", "1"} and not _field_value(
            relationship.find("otherText")
        ):
            _add_condition(
                anomalies,
                accession,
                "missing_other_text",
                "otherText is required when isOther is true",
            )

    for transaction in root.iter("derivativeTransaction"):
        amounts = transaction.find("transactionAmounts")
        if amounts is not None:
            _exactly_one_value(
                amounts,
                ("transactionShares", "transactionTotalValue"),
                anomalies,
                accession,
                "cm4_transaction_amount",
            )

    for ownership in root.iter("ownershipNature"):
        owner_type = _field_value(ownership.find("directOrIndirectOwnership"))
        nature = _field_value(ownership.find("natureOfOwnership"))
        if owner_type == "I" and not nature:
            _add_condition(
                anomalies,
                accession,
                "missing_indirect_ownership_nature",
                "natureOfOwnership is required for indirect ownership",
            )
        elif owner_type == "D" and nature:
            _add_condition(
                anomalies,
                accession,
                "nature_for_direct_ownership",
                "natureOfOwnership must be empty for direct ownership",
            )

    for parent_tag, fields, condition in (
        (
            "underlyingSecurity",
            ("underlyingSecurityShares", "underlyingSecurityValue"),
            "cm6_underlying_security",
        ),
        (
            "postTransactionAmounts",
            ("sharesOwnedFollowingTransaction", "valueOwnedFollowingTransaction"),
            "cm7_post_transaction_amount",
        ),
    ):
        for parent in root.iter(parent_tag):
            _exactly_one_value(parent, fields, anomalies, accession, condition)

    for field in root.iter():
        value = field.find("value")
        if value is not None and not (value.text or "").strip():
            footnoted = any(
                (footnote.text or "").strip()
                for footnote in field.findall("footnoteId")
            )
            if not footnoted:
                _add_condition(
                    anomalies,
                    accession,
                    "unfootnoted_empty_value",
                    f"empty {field.tag}/value must be footnoted",
                )

    for address in root.iter("reportingOwnerAddress"):
        flag = address.find("rptOwnerNonUSAddressFlag")
        flag_text = (flag.text or "").strip().lower() if flag is not None else ""
        if flag_text not in {"true", "false", "1", "0"}:
            _add_condition(
                anomalies,
                accession,
                "missing_non_us_address_flag",
                "rptOwnerNonUSAddressFlag is required when reportingOwnerAddress is present",
            )
        elif flag_text in {"true", "1"} and not _field_value(
            address.find("rptOwnerCountry")
        ):
            _add_condition(
                anomalies,
                accession,
                "missing_non_us_owner_country",
                "rptOwnerCountry is required for a non-US address",
            )
        elif flag_text in {"false", "0"} and not _field_value(
            address.find("rptOwnerState")
        ):
            _add_condition(
                anomalies,
                accession,
                "missing_us_owner_state",
                "rptOwnerState is required for a US address",
            )
    return anomalies


__all__ = ["ownership_schema_anomalies"]
