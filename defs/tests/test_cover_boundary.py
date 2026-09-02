"""Contract tests for the shared cover-boundary detector."""

from __future__ import annotations

import importlib

import pytest

cover_mod = importlib.import_module("defs.sec_forms.cover")
boundary_mod = importlib.import_module("defs.sec_forms.cover.boundary")

BoundaryInput = cover_mod.BoundaryInput
BoundaryMethod = cover_mod.BoundaryMethod
BoundarySignal = cover_mod.BoundarySignal
BodyRoot = cover_mod.BodyRoot
CoverBoundaryPolicy = cover_mod.CoverBoundaryPolicy
CoverStart = cover_mod.CoverStart
from defs.sec_forms.cover.rules import compile_cover_rules

find_cover_start = cover_mod.find_cover_start
find_page_markers = cover_mod.find_page_markers
get_profile = cover_mod.get_profile

ANNUAL_PROFILE = get_profile("10-K")
QUARTERLY_PROFILE = get_profile("10-Q")
ANNUAL_POLICY = ANNUAL_PROFILE.boundary
QUARTERLY_POLICY = QUARTERLY_PROFILE.boundary


def find_cover_boundary(
    boundary_input,
    policy=ANNUAL_POLICY,
    *,
    cover_evidence=None,
    body_evidence=None,
):
    if cover_evidence is None and body_evidence is None:
        if policy is ANNUAL_POLICY or (
            policy
            and BoundarySignal.INCORPORATED_REFERENCE in getattr(policy, "signals", ())
        ):
            cover_evidence = ANNUAL_PROFILE.cover_evidence
            body_evidence = ANNUAL_PROFILE.body_evidence
        elif policy is QUARTERLY_POLICY:
            cover_evidence = QUARTERLY_PROFILE.cover_evidence
            body_evidence = QUARTERLY_PROFILE.body_evidence
    return cover_mod.find_cover_boundary(
        boundary_input,
        policy,
        cover_evidence=cover_evidence,
        body_evidence=body_evidence,
    )


ANNUAL_COVER = """\
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
WASHINGTON, D.C. 20549
FORM 10-K
For the fiscal year ended December 31, 2024
Commission file number 001-13665
ACME CORPORATION
(Exact name of registrant as specified in its charter)
Delaware          12-3456789
(State or other jurisdiction of incorporation or organization)
Documents incorporated by reference: Portions of Part III.\
"""

ANNUAL_COVER_PLUS_BODY = (
    ANNUAL_COVER
    + """
PART I

Item 1. Business

The Company was incorporated in Delaware in 1985 and manufactures widgets for \
industrial customers throughout North America and Europe.\
"""
)


def test_none_policy_is_explicitly_disabled() -> None:
    boundary = find_cover_boundary(ANNUAL_COVER, None)
    assert boundary.end_line is None
    assert boundary.method is BoundaryMethod.DISABLED
    assert boundary.confidence == 0.0


def test_empty_text_is_unknown() -> None:
    boundary = find_cover_boundary("", ANNUAL_POLICY)
    assert boundary.end_line is None
    assert boundary.method is BoundaryMethod.UNKNOWN


def test_annual_incorporated_reference_ends_cover() -> None:
    boundary = find_cover_boundary(ANNUAL_COVER_PLUS_BODY, ANNUAL_POLICY)
    assert boundary.method is BoundaryMethod.STRUCTURAL
    assert boundary.end_line == 11
    assert boundary.continued_cover is True
    assert boundary.confidence >= 0.8
    names = {evidence.name for evidence in boundary.evidence}
    assert "incorporated_reference" in names
    assert "incorporated_reference_transition" in names
    assert boundary.end_offset is not None
    lines = ANNUAL_COVER_PLUS_BODY.splitlines()
    joined = "\n".join(lines[: boundary.end_line])
    assert "Documents incorporated by reference" in joined
    assert "Item 1. Business" not in joined


def test_embedded_part_list_is_not_cover_transition() -> None:
    text = ANNUAL_COVER.rsplit("\n", 1)[0]
    text += """
Documents incorporated by
reference: Parts I, II, and III are included in the proxy statement.
PART I. PART II.

PART I
Item 1. Business
"""
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    lines = text.splitlines()
    assert lines[boundary.end_line].strip() == "PART I"


def test_split_incorporated_reference_uses_later_single_heading() -> None:
    text = ANNUAL_COVER.rsplit("\n", 1)[0]
    text += "\nDocuments incorporated\nby reference: Portions of Part III.\n\nITEM 1. BUSINESS\n"
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    lines = text.splitlines()
    assert lines[boundary.end_line].strip() == "ITEM 1. BUSINESS"
    assert "incorporated_reference_transition" in {
        evidence.name for evidence in boundary.evidence
    }


def test_same_line_part_reference_is_not_a_cover_transition() -> None:
    text = ANNUAL_COVER.rsplit("\n", 1)[0]
    text += """
Documents incorporated by reference: Portions of the proxy statement are incorporated into
Part III. hereof.

PART I
ITEM 1. BUSINESS
The company operates worldwide.
"""
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    lines = text.splitlines()
    assert lines[boundary.end_line].strip() == "PART I"


def test_backward_confirmation_does_not_pull_boundary_into_reference_prose() -> None:
    text = ANNUAL_COVER.rsplit("\n", 1)[0]
    text += "\nPART I. PART II. are included by reference.\n"
    text += "Additional incorporated-reference continuation.\n" * 12
    text += "TABLE OF CONTENTS\nPART I ........................ 1\n"
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    lines = text.splitlines()
    assert lines[boundary.end_line].strip() == "TABLE OF CONTENTS"


def test_cover_start_constrains_forward_phrase_search() -> None:
    prelude = "Documents incorporated by reference appears in an exhibit.\n"
    text = prelude * 4 + ANNUAL_COVER.rsplit("\n", 1)[0]
    text += "\nDocuments incorporated by reference: None.\nPART I\n"
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    assert boundary.start_line >= 4
    assert boundary.end_line > boundary.start_line
    incorporated = next(
        evidence
        for evidence in boundary.evidence
        if evidence.name == "incorporated_reference"
    )
    assert incorporated.line >= boundary.start_line


def test_toc_transition_ends_cover_before_heading() -> None:
    text = ANNUAL_COVER.rsplit("\n", 1)[0]
    text += "\n\nTABLE OF CONTENTS\n\nPART I\nItem 1. Business\n"
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    assert boundary.method is BoundaryMethod.STRUCTURAL
    lines = text.splitlines()
    assert lines[boundary.end_line].strip().lower() == "table of contents"


def test_part_item_fallback_ends_cover() -> None:
    text = ANNUAL_COVER.rsplit("\n", 1)[0]
    text += "\n\nPART I\n\nItem 1. Business\n\nWe manufacture widgets.\n"
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    assert boundary.method is BoundaryMethod.FALLBACK
    lines = text.splitlines()
    assert lines[boundary.end_line].strip().lower() == "part i"


def test_boundary_phrase_in_body_prose_does_not_end_cover() -> None:
    text = """\
The Company hereby confirms that documents incorporated by reference
remain available for inspection during ordinary business hours and
that copies may be obtained from the registrant upon written request.\
"""
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    assert boundary.end_line is None
    assert boundary.method is BoundaryMethod.UNKNOWN


def test_quarterly_policy_excludes_incorporated_reference() -> None:
    assert BoundarySignal.INCORPORATED_REFERENCE not in QUARTERLY_POLICY.signals
    text = ANNUAL_COVER.rsplit("\n", 1)[0]
    text += "\nDocuments incorporated by reference: none.\n\nPART I\n"
    boundary = find_cover_boundary(text, QUARTERLY_POLICY)
    assert boundary.method is not BoundaryMethod.PHRASE
    lines = text.splitlines()
    assert lines[boundary.end_line].strip().lower() == "part i"


def test_cover_only_fragment_falls_back_to_full_cover() -> None:
    fragment = ANNUAL_COVER.rsplit("\n", 1)[0]
    boundary = find_cover_boundary(fragment, ANNUAL_POLICY)
    assert boundary.method is BoundaryMethod.FALLBACK
    assert boundary.end_line == len(fragment.splitlines())
    assert boundary.continued_cover is True
    assert boundary.approximate is True


def test_long_document_without_anchors_stays_unknown() -> None:
    filler = "\n".join(
        f"The Company discusses operating segment {index} results in detail."
        for index in range(600)
    )
    text = "SECURITIES AND EXCHANGE COMMISSION\nFORM 10-K\n" + filler
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    assert boundary.end_line is None
    assert boundary.method is BoundaryMethod.UNKNOWN


def test_page_marker_and_identity_evidence_is_recorded() -> None:
    text = ANNUAL_COVER.rsplit("\n", 1)[0]
    text = "<PAGE>\n" + text + "\n</PAGE>\n\nPART I\n"
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    names = {evidence.name for evidence in boundary.evidence}
    assert "first_page_marker" in names or "cover_identity_layout" in names


def test_page_marker_detector_returns_supported_spans() -> None:
    text = "-1-\nPage 2\n2 of 125\n<PAGE>     3\nF-1\n"
    markers = find_page_markers(text)
    assert [marker.kind for marker in markers] == [
        "dashed_number",
        "page_number",
        "number_of_total",
        "sgml",
    ]
    assert [marker.page_number for marker in markers] == [1, 2, 2, 3]
    assert all(text[marker.start : marker.end] == marker.text for marker in markers)


def test_letter_number_page_marker_requires_explicit_opt_in() -> None:
    text = "F-1\n"
    assert find_page_markers(text) == ()
    markers = find_page_markers(text, allow_letter_number=True)
    assert len(markers) == 1
    assert markers[0].kind == "letter_number"


def test_boundary_input_defaults_to_ascii_representation() -> None:
    boundary_input = BoundaryInput(ANNUAL_COVER)
    assert boundary_input.representation == "ascii"
    boundary = find_cover_boundary(boundary_input, ANNUAL_POLICY)
    assert boundary.method is BoundaryMethod.PHRASE
    assert boundary.continued_cover is True


def test_policy_without_signals_never_selects_boundary() -> None:
    boundary = find_cover_boundary(ANNUAL_COVER, CoverBoundaryPolicy(signals=()))
    assert boundary.end_line is None
    assert boundary.method is BoundaryMethod.UNKNOWN


ANNUAL_COVER_WITH_HEADER = """\
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
WASHINGTON, D.C. 20549
FORM 10-K
For the fiscal year ended December 31, 2024
Commission file number 001-13665
ACME CORPORATION
(Exact name of registrant as specified in its charter)
Delaware          12-3456789
(State or other jurisdiction of incorporation or organization)
"""


def test_find_cover_start_returns_inclusive_cluster_start() -> None:
    start = find_cover_start(ANNUAL_COVER_WITH_HEADER, ANNUAL_POLICY)
    assert start.start_line == 1
    assert start.start_offset == len("UNITED STATES\n")
    assert start.evidence
    names = {evidence.name for evidence in start.evidence}
    assert "cover_start_identity" in names
    assert "cover_start_shape" in names


def test_find_cover_start_returns_identity_and_shape_evidence() -> None:
    start = find_cover_start(ANNUAL_COVER_WITH_HEADER, ANNUAL_POLICY)
    evidence = list(start.evidence)
    assert any(e.name == "cover_start_identity" for e in evidence)
    assert any(e.name == "cover_start_shape" for e in evidence)
    identity = next(e for e in evidence if e.name == "cover_start_identity")
    shape = next(e for e in evidence if e.name == "cover_start_shape")
    assert identity.strength >= shape.strength


def test_find_cover_start_requires_both_identity_and_shape() -> None:
    text = "Some preamble text without cover signals.\n" * 10
    start = find_cover_start(text, ANNUAL_POLICY)
    assert start.start_line is None
    assert start.evidence == ()


def test_find_cover_start_returns_none_for_disabled_signal() -> None:
    policy = CoverBoundaryPolicy(signals=(BoundarySignal.PAGE_MARKERS,))
    start = find_cover_start(ANNUAL_COVER_WITH_HEADER, policy)
    assert start.start_line is None
    assert start.evidence == ()


def test_find_cover_start_returns_none_when_only_identity_present() -> None:
    text = "SECURITIES AND EXCHANGE COMMISSION\nFORM 10-K\nSome other text.\n"
    start = find_cover_start(text, ANNUAL_POLICY)
    assert start.start_line is None


def test_find_cover_start_returns_none_when_only_shape_present() -> None:
    text = "accelerated filer\nshell company\nSome other text.\n"
    start = find_cover_start(text, ANNUAL_POLICY)
    assert start.start_line is None


def test_find_cover_start_respects_cluster_gap() -> None:
    text = (
        "SECURITIES AND EXCHANGE COMMISSION\n"
        "FORM 10-K\n"
        "\n\n\n\n\n\n\n\n\n\n"
        "accelerated filer\n"
    )
    start = find_cover_start(text, ANNUAL_POLICY)
    assert start.start_line is None


def test_find_cover_start_none_policy_returns_unknown() -> None:
    start = find_cover_start(ANNUAL_COVER_WITH_HEADER, None)
    assert start.start_line is None
    assert start.start_offset is None


def test_find_cover_start_empty_text_returns_unknown() -> None:
    start = find_cover_start("", ANNUAL_POLICY)
    assert start.start_line is None


def test_cover_boundary_includes_start_fields() -> None:
    boundary = find_cover_boundary(ANNUAL_COVER_PLUS_BODY, ANNUAL_POLICY)
    assert boundary.start_line == 1
    assert boundary.start_offset == len("UNITED STATES\n")
    assert boundary.start_evidence
    names = {evidence.name for evidence in boundary.start_evidence}
    assert "cover_start_identity" in names
    assert "cover_start_shape" in names


def test_cover_boundary_start_fields_are_none_when_absent() -> None:
    boundary = find_cover_boundary("", ANNUAL_POLICY)
    assert boundary.start_line is None
    assert boundary.start_offset is None
    assert boundary.start_evidence == ()


def test_cover_start_default_offset_matches_line_zero() -> None:
    text = "SECURITIES AND EXCHANGE COMMISSION\nFORM 10-K\nCommission file number 123\n"
    start = find_cover_start(text, ANNUAL_POLICY)
    assert start.start_line == 0
    assert start.start_offset == 0


def test_adversarial_same_line_part_continuation_not_boundary() -> None:
    text = ANNUAL_COVER.rsplit("\n", 1)[0]
    text += "\nDocuments incorporated by reference: see Part III hereof.\n"
    text += "More reference prose about Part III.\n\n"
    text += "PART I\nITEM 1. BUSINESS\nThe company operates worldwide.\n"
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    lines = text.splitlines()
    assert lines[boundary.end_line].strip() == "PART I"


def test_adversarial_part_iv_abbreviation_not_boundary() -> None:
    text = ANNUAL_COVER.rsplit("\n", 1)[0]
    text += "\nIncorporated by reference: Part IV of this filing.\n\n"
    text += "PART I\nITEM 1. BUSINESS\nThe company operates.\n"
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    lines = text.splitlines()
    assert lines[boundary.end_line].strip() == "PART I"


def test_adversarial_item_one_toc_with_dot_leaders_not_body() -> None:
    text = ANNUAL_COVER.rsplit("\n", 1)[0]
    text += "\n\nTABLE OF CONTENTS\n"
    text += "PART I ........................................ 1\n"
    text += "ITEM 1. BUSINESS .......................... 1\n"
    text += "ITEM 1A. RISK FACTORS ..................... 8\n"
    text += "\nPART I\nITEM 1. BUSINESS\nThe company operates.\n"
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    lines = text.splitlines()
    assert lines[boundary.end_line].strip().lower() == "table of contents"


def test_adversarial_forward_looking_does_not_move_cover_end() -> None:
    text = ANNUAL_COVER.rsplit("\n", 1)[0]
    text += "\n\nForward-Looking Statements\n\n"
    text += "This filing contains forward-looking statements.\n" * 5
    text += "\nPART I\nITEM 1. BUSINESS\nThe company operates.\n"
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    lines = text.splitlines()
    assert lines[boundary.end_line].strip() == "PART I"


def test_adversarial_backward_confirm_respects_toc_boundary() -> None:
    text = ANNUAL_COVER.rsplit("\n", 1)[0]
    text += "\n\nTABLE OF CONTENTS\n"
    text += "ITEM 1. BUSINESS .......................... 1\n"
    text += "ITEM 2. PROPERTIES ....................... 5\n"
    text += "\nPART I\nITEM 1. BUSINESS\nThe company operates.\n"
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    lines = text.splitlines()
    assert lines[boundary.end_line].strip().lower() == "table of contents"


def test_positive_standard_annual_cover_boundary() -> None:
    boundary = find_cover_boundary(ANNUAL_COVER_PLUS_BODY, ANNUAL_POLICY)
    assert boundary.method is BoundaryMethod.STRUCTURAL
    assert boundary.continued_cover is True
    assert boundary.confidence >= 0.8
    assert boundary.start_line is not None
    assert boundary.start_line >= 0


def test_positive_toc_heading_ends_cover() -> None:
    text = ANNUAL_COVER.rsplit("\n", 1)[0]
    text += "\n\nTABLE OF CONTENTS\n\nPART I\nItem 1. Business\n"
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    assert boundary.method is BoundaryMethod.STRUCTURAL
    lines = text.splitlines()
    assert lines[boundary.end_line].strip().lower() == "table of contents"


def test_positive_page_marker_evidence_recorded() -> None:
    text = "<PAGE>\n" + ANNUAL_COVER.rsplit("\n", 1)[0] + "\n</PAGE>\n\nPART I\n"
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    names = {evidence.name for evidence in boundary.evidence}
    assert "first_page_marker" in names or "cover_identity_layout" in names


def test_positive_quarterly_excludes_incorporated_reference() -> None:
    assert BoundarySignal.INCORPORATED_REFERENCE not in QUARTERLY_POLICY.signals
    text = ANNUAL_COVER.rsplit("\n", 1)[0]
    text += "\nDocuments incorporated by reference: none.\n\nPART I\n"
    boundary = find_cover_boundary(text, QUARTERLY_POLICY)
    assert boundary.method is not BoundaryMethod.PHRASE


def test_positive_no_cover_profile_disabled() -> None:
    boundary = find_cover_boundary(ANNUAL_COVER_PLUS_BODY, None)
    assert boundary.method is BoundaryMethod.DISABLED
    assert boundary.end_line is None


def test_positive_cover_start_cluster_detected() -> None:
    start = find_cover_start(ANNUAL_COVER_WITH_HEADER, ANNUAL_POLICY)
    assert start.start_line is not None
    assert start.start_line >= 0
    names = {evidence.name for evidence in start.evidence}
    assert "cover_start_identity" in names
    assert "cover_start_shape" in names


def test_positive_boundary_includes_start_fields() -> None:
    boundary = find_cover_boundary(ANNUAL_COVER_PLUS_BODY, ANNUAL_POLICY)
    assert boundary.start_line is not None
    assert boundary.start_offset is not None
    assert boundary.start_evidence


def test_positive_empty_text_unknown() -> None:
    boundary = find_cover_boundary("", ANNUAL_POLICY)
    assert boundary.method is BoundaryMethod.UNKNOWN
    assert boundary.end_line is None


def test_adversarial_part_reference_prose_line_not_boundary() -> None:
    text = ANNUAL_COVER.rsplit("\n", 1)[0]
    text += "\nDocuments incorporated by reference: Portions of\n"
    text += "Part III of this report.\n\nPART I\nITEM 1. BUSINESS\n"
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    lines = text.splitlines()
    assert lines[boundary.end_line].strip() == "PART I"


def test_adversarial_part_heading_lowercase_continuation_not_boundary() -> None:
    text = ANNUAL_COVER.rsplit("\n", 1)[0]
    text += "\nDocuments incorporated by reference include\n"
    text += "Part I\nand Part II of the proxy statement.\n\n"
    text += "PART I\nITEM 1. BUSINESS\nThe company operates.\n"
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    lines = text.splitlines()
    assert lines[boundary.end_line].strip() == "PART I"


def test_positive_part_item_pair_sentinel() -> None:
    text = ANNUAL_COVER.rsplit("\n", 1)[0]
    text += "\n\nPART I\n\nITEM 1. BUSINESS\n\nThe company operates worldwide.\n"
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    lines = text.splitlines()
    assert lines[boundary.end_line].strip() == "PART I"
    names = {evidence.name for evidence in boundary.evidence}
    assert "part_item_pair" in names


@pytest.mark.parametrize(
    "title",
    [
        "BUSINESS",
        "General Business Operations",
        "Description of Business",
        "Business of the Company",
    ],
)
def test_positive_item_title_variations_recognized(title: str) -> None:
    text = ANNUAL_COVER.rsplit("\n", 1)[0]
    text += f"\n\nITEM 1. {title}\n"
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    lines = text.splitlines()
    assert lines[boundary.end_line].strip().upper() == f"ITEM 1. {title}".upper()


def test_positive_collapsed_pair_with_period_and_title() -> None:
    text = ANNUAL_COVER.rsplit("\n", 1)[0]
    text += "\n\nPART I.\nItem 1.  Business.\nThe company operates.\n"
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    lines = text.splitlines()
    assert lines[boundary.end_line].strip() == "PART I."
    names = {evidence.name for evidence in boundary.evidence}
    assert "part_item_pair" in names


def test_positive_item_dash_separator_heading() -> None:
    text = ANNUAL_COVER.rsplit("\n", 1)[0]
    text += "\n\nITEM 1 -- BUSINESS\nThe company operates.\n"
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    lines = text.splitlines()
    assert lines[boundary.end_line].strip() == "ITEM 1 -- BUSINESS"


def test_adversarial_toc_item_row_with_page_suffix_not_heading() -> None:
    text = ANNUAL_COVER.rsplit("\n", 1)[0]
    text += "\n\nITEM 1. BUSINESS                    3\n"
    text += "PART I ............................ 1\n\n"
    text += "PART I\nITEM 1. BUSINESS\nThe company operates.\n"
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    lines = text.splitlines()
    assert lines[boundary.end_line].strip() == "PART I"


ANNUAL_COVER_WITH_BODY = """\
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
WASHINGTON, D.C. 20549
FORM 10-K
For the fiscal year ended December 31, 2024
Commission file number 001-13665
ACME CORPORATION
(Exact name of registrant as specified in its charter)
Delaware          12-3456789
(State or other jurisdiction of incorporation or organization)

PART I

Item 1. Business

The Company was incorporated in Delaware in 1985 and operates manufacturing
facilities throughout North America and Europe. It provides products to
customers worldwide.\
"""


def test_backward_confirm_boosts_confidence_when_body_root_close() -> None:
    boundary = find_cover_boundary(ANNUAL_COVER_WITH_BODY, ANNUAL_POLICY)
    names = {evidence.name for evidence in boundary.evidence}
    assert "backward_body_confirm" in names


def test_backward_adjust_pulls_back_to_body_root() -> None:
    from defs.sec_forms.cover.boundary import _confirm_backward_body

    lines = ANNUAL_COVER_WITH_BODY.splitlines()
    evidence: list = []
    adjusted_end, updated_evidence = _confirm_backward_body(lines, 50, 0, evidence)
    assert adjusted_end < 50
    assert any(e.name == "backward_body_adjust" for e in updated_evidence)


def test_backward_search_finds_structural_part_one() -> None:
    from defs.sec_forms.cover.boundary import _find_body_root_backward

    lines = ANNUAL_COVER_WITH_BODY.splitlines()
    root = _find_body_root_backward(lines, len(lines), 0)
    assert root is not None
    assert root.root_type == "structural"
    assert "PART I" in root.label or "Item" in root.label


def test_backward_search_finds_part_one_before_items() -> None:
    from defs.sec_forms.cover.boundary import _find_body_root_backward

    lines = ANNUAL_COVER_WITH_BODY.splitlines()
    root = _find_body_root_backward(lines, 12, 0)
    assert root is not None
    assert root.root_type == "structural"
    assert "PART I" in root.label


def test_backward_search_finds_semantic_heading() -> None:
    from defs.sec_forms.cover.boundary import _find_body_root_backward

    text = ANNUAL_COVER + "\n\nManagement's Discussion and Analysis\n\nSome text.\n"
    lines = text.splitlines()
    rules = compile_cover_rules(
        ANNUAL_PROFILE.cover_evidence, ANNUAL_PROFILE.body_evidence
    )
    root = _find_body_root_backward(lines, len(lines), 0, rules=rules)
    assert root is not None
    assert root.root_type == "semantic"


def test_backward_search_finds_substantive_paragraph() -> None:
    from defs.sec_forms.cover.boundary import _find_body_root_backward

    text = (
        ANNUAL_COVER
        + "\n\nThe Company operates manufacturing facilities and provides\n"
        + "products to customers through its market segments worldwide.\n"
    )
    lines = text.splitlines()
    rules = compile_cover_rules(
        ANNUAL_PROFILE.cover_evidence, ANNUAL_PROFILE.body_evidence
    )
    root = _find_body_root_backward(lines, len(lines), 0, rules=rules)
    assert root is not None
    assert root.root_type == "substantive"


def test_backward_search_respects_search_limit() -> None:
    from defs.sec_forms.cover.boundary import _find_body_root_backward

    filler = "\n".join(f"Line {index}" for index in range(300))
    text = ANNUAL_COVER + "\n\nPART I\n" + filler
    lines = text.splitlines()
    root = _find_body_root_backward(lines, len(lines), 0)
    assert root is None or root.line < len(lines) - 150


def test_backward_search_none_outside_corridor() -> None:
    from defs.sec_forms.cover.boundary import _find_body_root_backward

    text = "PART I\n" + "\n".join(f"Line {index}" for index in range(300))
    lines = text.splitlines()
    root = _find_body_root_backward(lines, len(lines), 0)
    assert root is None


def test_body_root_dataclass_is_frozen() -> None:
    root = BodyRoot(line=10, root_type="structural", confidence=0.95, label="PART I")
    assert root.line == 10
    assert root.root_type == "structural"
    with pytest.raises(AttributeError):
        root.line = 20


def test_adversarial_part_with_numbered_list_not_boundary() -> None:
    text = (
        ANNUAL_COVER.rsplit("\n", 1)[0]
        + """
DOCUMENTS INCORPORATED BY REFERENCE

Part I

1. Portions of the 2024 Annual Report to Shareholders.
2. Description of registrant common stock.

Part III

Portions of the definitive Proxy Statement for the 2025 Annual Meeting.

PART I

ITEM 1. BUSINESS

The Company operates manufacturing facilities worldwide.
"""
    )
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    lines = text.splitlines()
    assert lines[boundary.end_line].strip() == "PART I"


def test_adversarial_part_with_preceding_include_colon_not_boundary() -> None:
    text = (
        ANNUAL_COVER.rsplit("\n", 1)[0]
        + """
Documents incorporated by reference include:
Part I.
Portions of the 2024 Annual Report to Shareholders.

PART I

ITEM 1. BUSINESS

The Company operates manufacturing facilities worldwide.
"""
    )
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    lines = text.splitlines()
    assert lines[boundary.end_line].strip() == "PART I"


def test_adversarial_part_with_dash_bullets_not_boundary() -> None:
    text = (
        ANNUAL_COVER.rsplit("\n", 1)[0]
        + """
DOCUMENTS INCORPORATED BY REFERENCE

Part I:
- some text from the annual report

Part II:
- some text from the proxy statement

PART I

ITEM 1. BUSINESS

The Company was incorporated in Delaware and operates manufacturing facilities worldwide.
"""
    )
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    lines = text.splitlines()
    assert lines[boundary.end_line].strip() == "PART I"


def test_positive_ascii_tagged_table_with_internal_part_rows() -> None:
    text = (
        ANNUAL_COVER.rsplit("\n", 1)[0]
        + """
DOCUMENTS INCORPORATED BY REFERENCE
<TABLE>
<CAPTION>
Part of Form 10-K             Document Incorporated
<S>                           <C>
Part I                        2024 Annual Report to Shareholders
Part III                      Definitive Proxy Statement
</TABLE>

PART I

ITEM 1. BUSINESS

The Company operates manufacturing facilities worldwide.
"""
    )
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    lines = text.splitlines()
    assert lines[boundary.end_line].strip() == "PART I"


def test_positive_ascii_untagged_table_with_internal_part_rows() -> None:
    text = (
        ANNUAL_COVER.rsplit("\n", 1)[0]
        + """
DOCUMENTS INCORPORATED BY REFERENCE

Part of Form 10-K           Document Incorporated by Reference
-----------------           ----------------------------------
Part I                      Annual Report to Shareholders
Part III                    Definitive Proxy Statement

PART I

ITEM 1. BUSINESS

The Company operates manufacturing facilities worldwide.
"""
    )
    boundary = find_cover_boundary(text, ANNUAL_POLICY)
    lines = text.splitlines()
    assert lines[boundary.end_line].strip() == "PART I"
