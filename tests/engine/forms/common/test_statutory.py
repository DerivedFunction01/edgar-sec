"""Unit tests for engine common statutory regexes."""

from edgar_sec.engine.forms.common.statutory import (
    CERTIFICATION_DECLARATION_RE,
    HEADER_LEAK_RE,
    OMB_BURDEN_RE,
    OMB_CONTROL_RE,
    OMB_NUMBER_RE,
    RULE_10B5_1_RE,
    STATUTORY_PAGE_ARTIFACT_RE,
    annotate_common_form_phrases,
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


def test_annotate_common_phrases_keeps_offsets_and_neighbor_context():
    text = (
        "Signature of reporting person\n"
        "Intentional misstatements or omissions of facts\n"
        "constitute Federal criminal violations.\n"
        "18 U.S.C. 1001\n"
    )

    matches = annotate_common_form_phrases(
        text,
        family_id="ownership",
        section_role="signatures",
        source_id="filing-1",
    )
    warning = next(
        match for match in matches if match.rule_id == "statutory.criminal_warning"
    )

    assert text[warning.start_offset : warning.end_offset] == warning.matched_text
    assert warning.matched_text.endswith("Federal criminal violations")
    assert warning.start_line == 2
    assert warning.end_line == 3
    assert warning.previous_lines == ("Signature of reporting person",)
    assert warning.next_lines == ("18 U.S.C. 1001",)
    assert warning.source_id == "filing-1"


def test_statutory_prompt_and_boilerplate_helpers():
    """Verify prompt prefix stripping and pure boilerplate detection."""
    from edgar_sec.engine.forms.common.statutory import (
        is_pure_statutory_boilerplate,
        strip_form_prompt_prefix,
    )

    prompt = "1(a) NAME OF ISSUER: Apple Inc."
    assert strip_form_prompt_prefix(prompt) == "Apple Inc."

    filer_prompt = "2(a) Name of person for whose account: Glenn Robinson"
    assert strip_form_prompt_prefix(filer_prompt) == "Glenn Robinson"

    assert is_pure_statutory_boilerplate("SEE INSTRUCTION 3(b)")
    assert is_pure_statutory_boilerplate("SECURITIES AND EXCHANGE COMMISSION")
    assert not is_pure_statutory_boilerplate("Apple Inc.")
    assert not is_pure_statutory_boilerplate("Glenn Robinson")
