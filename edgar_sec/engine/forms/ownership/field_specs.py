from edgar_sec.domain.forms.families.ownership.taxonomy import (
    OWNERSHIP_ACQUIRED_DISPOSED_CODES,
    OWNERSHIP_DOCUMENT_TYPES,
    OWNERSHIP_STATE_CODES,
    OWNERSHIP_TIMELINESS_CODES,
    OWNERSHIP_TYPE_CODES,
    VALID_TRANSACTION_CODES,
)
from edgar_sec.domain.taxonomy.jurisdictions import EDGAR_JURISDICTION_CODES
from edgar_sec.engine.forms.common.extraction import FieldKind, FieldSpec

_COUNTRY_CODES = EDGAR_JURISDICTION_CODES - OWNERSHIP_STATE_CODES
_XML_BOOLEAN_VALUES = frozenset({"true", "false", "1", "0"})

OWNERSHIP_SCHEMA_FIELDS = (
    FieldSpec(
        "documentType",
        FieldKind.ENUM,
        allowed_values=OWNERSHIP_DOCUMENT_TYPES,
        anomaly_kind="invalid_document_type",
        detail="documentType is not permitted by the ownership schema",
    ),
    FieldSpec(
        "transactionCode",
        FieldKind.ENUM,
        value_child=True,
        allowed_values=VALID_TRANSACTION_CODES,
        anomaly_kind="invalid_transaction_code",
        detail="transactionCode is not in the ownership schema list",
    ),
    FieldSpec(
        "transactionAcquiredDisposedCode",
        FieldKind.ENUM,
        value_child=True,
        allowed_values=OWNERSHIP_ACQUIRED_DISPOSED_CODES,
        anomaly_kind="invalid_transactionAcquiredDisposedCode",
        detail="transactionAcquiredDisposedCode must be A or D",
    ),
    FieldSpec(
        "rptOwnerState",
        FieldKind.ENUM,
        allowed_values=OWNERSHIP_STATE_CODES,
        anomaly_kind="invalid_rptOwnerState",
        detail="rptOwnerState is not in its ownership schema choice list",
    ),
    FieldSpec(
        "rptOwnerCountry",
        FieldKind.ENUM,
        allowed_values=_COUNTRY_CODES,
        anomaly_kind="invalid_rptOwnerCountry",
        detail="rptOwnerCountry is not in its ownership schema choice list",
    ),
    FieldSpec(
        "directOrIndirectOwnership",
        FieldKind.ENUM,
        value_child=True,
        allowed_values=OWNERSHIP_TYPE_CODES,
        anomaly_kind="invalid_directOrIndirectOwnership",
        detail="directOrIndirectOwnership is not in its ownership schema choice list",
    ),
    FieldSpec(
        "transactionTimeliness",
        FieldKind.ENUM,
        value_child=True,
        allowed_values=OWNERSHIP_TIMELINESS_CODES,
        anomaly_kind="invalid_transactionTimeliness",
        detail="transactionTimeliness is not in its ownership schema choice list",
    ),
    *(
        FieldSpec(
            field,
            FieldKind.ENUM,
            allowed_values=_XML_BOOLEAN_VALUES,
            anomaly_kind=f"invalid_{field}",
            detail=f"{field} must use an XML Schema boolean value",
        )
        for field in (
            "isDirector",
            "isOfficer",
            "isTenPercentOwner",
            "isOther",
            "equitySwapInvolved",
            "rptOwnerNonUSAddressFlag",
        )
    ),
    *(
        FieldSpec(
            field,
            FieldKind.DECIMAL,
            value_child=True,
            minimum="0",
            maximum="999999999999.9999",
            max_scale=4,
            anomaly_kind=f"invalid_{field}_decimal",
            detail=f"{field} must be a nonnegative schema decimal in range",
        )
        for field in (
            "conversionOrExercisePrice",
            "transactionShares",
            "transactionPricePerShare",
            "transactionTotalValue",
            "sharesOwnedFollowingTransaction",
            "valueOwnedFollowingTransaction",
            "underlyingSecurityShares",
            "underlyingSecurityValue",
        )
    ),
)

__all__ = ["OWNERSHIP_SCHEMA_FIELDS"]
