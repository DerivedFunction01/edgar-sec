"""Form 144 schema code sets."""

FORM144_SUBMISSION_TYPES = frozenset({"144", "144/A"})
FORM144_LIVE_TEST_TYPES = frozenset({"LIVE", "TEST"})
FORM144_RELATIONSHIPS_TO_ISSUER = frozenset(
    {
        "Officer",
        "Director",
        "10% Stockholder",
        "Member of immediate family of any of the foregoing",
        "Provide any other relationship not mentioned above",
    }
)
FORM144_YES_NO_CODES = frozenset({"Y", "N"})

__all__ = [
    "FORM144_LIVE_TEST_TYPES",
    "FORM144_RELATIONSHIPS_TO_ISSUER",
    "FORM144_SUBMISSION_TYPES",
    "FORM144_YES_NO_CODES",
]
