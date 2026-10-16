"""Unit tests for engine common statutory regexes."""

from edgar_sec.engine.forms.common.statutory import (
    CERTIFICATION_DECLARATION_RE,
    HEADER_LEAK_RE,
    OMB_BURDEN_RE,
    OMB_CONTROL_RE,
    OMB_NUMBER_RE,
    RULE_10B5_1_RE,
    STATUTORY_PAGE_ARTIFACT_RE,
)


def test_header_leak_and_statutory_artifact_matching():
    """Verify detection of header leaks and statutory artifacts."""
    assert bool(HEADER_LEAK_RE.search("date of original filing"))
    assert bool(STATUTORY_PAGE_ARTIFACT_RE.search("see instruction 6 for procedure"))


def test_omb_rule10b5_and_certifications():
    """Verify OMB numbers, burden notices, 10b5-1, and certification declarations."""
    m_omb = OMB_CONTROL_RE.search("OMB Number: 3235-0101")
    assert m_omb is not None
    assert m_omb.group(1) == "3235-0101"
    assert bool(OMB_NUMBER_RE.search("Form 144 (OMB 3235-0101)"))
    assert bool(
        OMB_BURDEN_RE.search("Estimated average burden hours per response: 1.0")
    )
    assert bool(
        RULE_10B5_1_RE.search(
            "Date of Plan Adoption or Giving of Instruction (if relying on Rule 10b5-1)"
        )
    )
    assert bool(
        CERTIFICATION_DECLARATION_RE.search(
            "I certify that the information set forth in this statement is true, complete and correct."
        )
    )
