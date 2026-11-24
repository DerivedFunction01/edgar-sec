"""Field metadata for ownership document analysis."""

from __future__ import annotations

FIELD_PATHS: dict[str, tuple[str, ...]] = {
    "periodOfReport": ("periodOfReport",),
    "issuerCik": ("issuer/issuerCik",),
    "issuerName": ("issuer/issuerName",),
    "issuerTradingSymbol": ("issuer/issuerTradingSymbol",),
    "rptOwnerCik": ("reportingOwner/reportingOwnerId/rptOwnerCik",),
    "rptOwnerName": ("reportingOwner/reportingOwnerId/rptOwnerName",),
    "isDirector": ("reportingOwner/reportingOwnerRelationship/isDirector",),
    "isOfficer": ("reportingOwner/reportingOwnerRelationship/isOfficer",),
    "isTenPercentOwner": (
        "reportingOwner/reportingOwnerRelationship/isTenPercentOwner",
    ),
    "isOther": ("reportingOwner/reportingOwnerRelationship/isOther",),
    "officerTitle": ("reportingOwner/reportingOwnerRelationship/officerTitle",),
    "otherText": ("reportingOwner/reportingOwnerRelationship/otherText",),
    "signatureName": ("ownerSignature/signatureName",),
    "signatureDate": ("ownerSignature/signatureDate",),
    "securityTitle": (
        "nonDerivativeTable/*/securityTitle/value",
        "derivativeTable/*/securityTitle/value",
    ),
    "transactionDate": (
        "nonDerivativeTable/*/transactionDate/value",
        "derivativeTable/*/transactionDate/value",
    ),
    "transactionCode": (
        "nonDerivativeTable/*/transactionCoding/transactionCode",
        "derivativeTable/*/transactionCoding/transactionCode",
    ),
    "transactionShares": (
        "nonDerivativeTable/*/transactionAmounts/transactionShares/value",
        "derivativeTable/*/transactionAmounts/transactionShares/value",
    ),
    "transactionPricePerShare": (
        "nonDerivativeTable/*/transactionAmounts/transactionPricePerShare/value",
        "derivativeTable/*/transactionAmounts/transactionPricePerShare/value",
    ),
    "transactionAcquiredDisposedCode": (
        "nonDerivativeTable/*/transactionAmounts/transactionAcquiredDisposedCode/value",
        "derivativeTable/*/transactionAmounts/transactionAcquiredDisposedCode/value",
    ),
    "sharesOwnedFollowingTransaction": (
        "nonDerivativeTable/*/postTransactionAmounts/sharesOwnedFollowingTransaction/value",
        "derivativeTable/*/postTransactionAmounts/sharesOwnedFollowingTransaction/value",
    ),
    "directOrIndirectOwnership": (
        "nonDerivativeTable/*/ownershipNature/directOrIndirectOwnership/value",
        "derivativeTable/*/ownershipNature/directOrIndirectOwnership/value",
    ),
    "natureOfOwnership": (
        "nonDerivativeTable/*/ownershipNature/natureOfOwnership/value",
    ),
    "conversionOrExercisePrice": ("derivativeTable/*/conversionOrExercisePrice/value",),
    "exerciseDate": (
        "derivativeTable/*/exerciseDateAndExpirationDate/exerciseDate/value",
    ),
    "expirationDate": (
        "derivativeTable/*/exerciseDateAndExpirationDate/expirationDate/value",
    ),
    "underlyingSecurityTitle": (
        "derivativeTable/*/underlyingSecurity/underlyingSecurityTitle/value",
    ),
    "underlyingSecurityShares": (
        "derivativeTable/*/underlyingSecurity/underlyingSecurityShares/value",
    ),
}

DOCUMENT_FIELDS = frozenset(
    {
        "periodOfReport",
        "issuerCik",
        "issuerName",
        "issuerTradingSymbol",
        "rptOwnerCik",
        "rptOwnerName",
        "isDirector",
        "isOfficer",
        "isTenPercentOwner",
        "isOther",
        "officerTitle",
        "otherText",
        "signatureName",
        "signatureDate",
    }
)
REQUIRED_DOCUMENT_FIELDS = (
    "periodOfReport",
    "issuerName",
    "issuerTradingSymbol",
    "rptOwnerName",
    "signatureName",
    "signatureDate",
)
UNAVAILABLE_DOCUMENT_FIELDS = (
    "issuerCik",
    "rptOwnerCik",
)
FIELD_VALUE_TAGS = {
    "securityTitle": "securityTitle",
    "underlyingSecurityTitle": "underlyingSecurityTitle",
    "officerTitle": "officerTitle",
    "signatureName": "signatureName",
    "rptOwnerName": "rptOwnerName",
    "transactionCode": "transactionCode",
    "transactionFormType": "transactionFormType",
    "equitySwapInvolved": "equitySwapInvolved",
    "transactionAcquiredDisposedCode": "transactionAcquiredDisposedCode",
    "directOrIndirectOwnership": "directOrIndirectOwnership",
    "natureOfOwnership": "natureOfOwnership",
    "isDirector": "isDirector",
    "isOfficer": "isOfficer",
    "isTenPercentOwner": "isTenPercentOwner",
    "isOther": "isOther",
}
FIELD_WORD_LIMITS: dict[str, int] = {
    "securityTitle": 7,
    "underlyingSecurityTitle": 7,
    "signatureName": 4,
    "officerTitle": 6,
    "rptOwnerName": 6,
}
