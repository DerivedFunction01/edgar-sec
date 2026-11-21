from edgar_sec.domain.forms.families.form144.taxonomy import (
    FORM144_RELATIONSHIPS_TO_ISSUER,
    FORM144_YES_NO_CODES,
)
from edgar_sec.domain.taxonomy.jurisdictions import EDGAR_JURISDICTION_CODES
from edgar_sec.engine.forms.common.extraction import FieldKind, FieldSpec

_TEXT_LIMITS = {
    "schemaVersion": 5,
    "previousAccessionNumber": 20,
    "cik": 10,
    "ccc": 8,
    "contactName": 30,
    "contactPhone": 20,
    "contactEmail": 80,
    "notificationEmail": 80,
    "issuerCik": 10,
    "issuerName": 150,
    "street1": 40,
    "street2": 40,
    "city": 30,
    "zipCode": 10,
    "issuerContactPhone": 20,
    "nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold": 150,
    "securitiesClassTitle": 150,
    "name": 100,
    "securitiesExchangeName": 20,
    "natureOfAcquisitionTransaction": 255,
    "nameOfPersonfromWhomAcquired": 100,
    "natureOfPayment": 255,
    "remarks": 1000,
    "signature": 150,
    "conformedName": 32,
    "conformedDocumentType": 255,
    "description": 255,
}

_MULTIPLE_OCCURRENCES = {
    "relationshipToIssuer": 5,
    "securitiesInformation": 40,
    "securitiesToBeSold": 40,
    "securitiesSoldInPast3Months": 200,
    "planAdoptionDate": 20,
    "notificationEmail": 3,
}

FORM144_FIELD_SPECS = (
    *(
        FieldSpec(
            field,
            FieldKind.TEXT,
            max_length=maximum,
            max_occurs=_MULTIPLE_OCCURRENCES.get(field),
            anomaly_kind=f"overlength_{field}",
            detail=f"{field} exceeds its {maximum}-character limit",
        )
        for field, maximum in _TEXT_LIMITS.items()
    ),
    FieldSpec(
        "stateOrCountry",
        FieldKind.ENUM,
        max_length=2,
        allowed_values=EDGAR_JURISDICTION_CODES,
        anomaly_kind="invalid_stateOrCountry",
        detail="Unsupported EDGAR jurisdiction code",
    ),
    FieldSpec(
        "relationshipToIssuer",
        FieldKind.ENUM,
        max_length=50,
        max_occurs=_MULTIPLE_OCCURRENCES["relationshipToIssuer"],
        allowed_values=FORM144_RELATIONSHIPS_TO_ISSUER,
        anomaly_kind="invalid_relationshipToIssuer",
        detail="Unsupported issuer relationship",
    ),
    *(
        FieldSpec(
            field,
            FieldKind.ENUM,
            max_length=1,
            allowed_values=FORM144_YES_NO_CODES,
            anomaly_kind=f"invalid_{field}",
            detail=f"{field} must be Y or N",
        )
        for field in (
            "isGiftTransaction",
            "nothingToReportFlagOnSecuritiesSoldInPast3Months",
        )
    ),
    *(
        FieldSpec(
            field,
            FieldKind.INTEGER,
            max_length=12,
            minimum="1" if field == "noOfUnitsSold" else "0",
            anomaly_kind="invalid_units"
            if field == "noOfUnitsSold"
            else f"invalid_{field}",
            detail=(
                "Units sold must be a positive schema integer"
                if field == "noOfUnitsSold"
                else f"{field} must be a nonnegative schema integer of at most 12 digits"
            ),
        )
        for field in (
            "noOfUnitsSold",
            "noOfUnitsOutstanding",
            "amountOfSecuritiesAcquired",
            "amountOfSecuritiesSold",
        )
    ),
    *(
        FieldSpec(
            field,
            FieldKind.DECIMAL,
            max_length=14,
            anomaly_kind=f"invalid_{field}",
            detail=f"{field} must be a schema decimal of at most 14 characters",
        )
        for field in ("aggregateMarketValue", "grossProceeds")
    ),
    *(
        FieldSpec(
            field,
            FieldKind.DATE,
            date_lexeme="MDY",
            max_occurs=_MULTIPLE_OCCURRENCES.get(field),
            anomaly_kind=f"invalid_{field}",
            detail=f"{field} must use MM-DD-YYYY",
        )
        for field in (
            "approxSaleDate",
            "acquiredDate",
            "donarAcquiredDate",
            "paymentDate",
            "saleDate",
            "noticeDate",
            "planAdoptionDate",
        )
    ),
    FieldSpec("securitiesInformation", FieldKind.TEXT, max_occurs=40),
    FieldSpec("securitiesToBeSold", FieldKind.TEXT, max_occurs=40),
    FieldSpec("securitiesSoldInPast3Months", FieldKind.TEXT, max_occurs=200),
)

__all__ = ["FORM144_FIELD_SPECS"]
