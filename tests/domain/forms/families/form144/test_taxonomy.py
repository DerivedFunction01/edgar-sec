from edgar_sec.domain.forms.families.form144.taxonomy import (
    FORM144_LIVE_TEST_TYPES,
    FORM144_RELATIONSHIPS_TO_ISSUER,
    FORM144_SUBMISSION_TYPES,
    FORM144_YES_NO_CODES,
)
from edgar_sec.domain.taxonomy.jurisdictions import EDGAR_JURISDICTION_CODES


def test_form144_schema_code_sets():
    assert FORM144_SUBMISSION_TYPES == {"144", "144/A"}
    assert FORM144_LIVE_TEST_TYPES == {"LIVE", "TEST"}
    assert FORM144_YES_NO_CODES == {"Y", "N"}
    assert "10% Stockholder" in FORM144_RELATIONSHIPS_TO_ISSUER
    assert "MA" in EDGAR_JURISDICTION_CODES
