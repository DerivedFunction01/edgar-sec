"""Contract tests for the cover search corridor."""

from __future__ import annotations

from edgar_sec.engine.forms.cover.boundary.corridor import (
    confirm_backward_body,
    enabled,
    find_cover_start,
    is_proxy_reference_disclosure,
    is_toc_like_line,
    line_at_offset,
    line_offset,
    next_nonblank_line,
    prev_nonblank_line,
)
from edgar_sec.engine.forms.cover.models import (
    BoundaryEvidence,
    BoundaryInput,
    BoundarySignal,
    CoverBoundaryPolicy,
)

COVER = (
    "UNITED STATES SECURITIES AND EXCHANGE COMMISSION\n"
    "Washington, D.C. 20549\n"
    "Commission File Number 001-12345\n"
    "Precise name of registrant as specified in Section 10(b)\n"
    "FORM 10-K\n"
    "PART I\n"
    "ITEM 1. BUSINESS\n"
    "The company operates worldwide and supplies customers.\n"
).splitlines()


def _policy(*signals: BoundarySignal) -> CoverBoundaryPolicy:
    return CoverBoundaryPolicy(signals=signals)


def test_offset_helpers_round_trip_to_the_same_line() -> None:
    assert line_offset(COVER, 0) == 0
    assert line_offset(COVER, 2) == len(COVER[0]) + 1 + len(COVER[1]) + 1
    assert line_at_offset("\n".join(COVER), line_offset(COVER, 3)) == 3


def test_blank_line_helpers_find_the_nearest_neighbours() -> None:
    lines = ["a", "", "b", "", "c"]

    assert prev_nonblank_line(lines, 4) == (4, "c")
    assert prev_nonblank_line(lines, 3) == (2, "b")
    assert next_nonblank_line(lines, 0) == (0, "a")
    assert next_nonblank_line(lines, 1) == (2, "b")
    assert prev_nonblank_line(["", ""], 1) is None
    assert next_nonblank_line(["a"], 1) is None


def test_toc_like_lines_are_recognized_in_every_layout() -> None:
    assert is_toc_like_line("ITEM 1. BUSINESS .... 1") is True
    assert is_toc_like_line("Item 1 - Business                    1") is True
    assert is_toc_like_line("1. Business") is True
    assert is_toc_like_line("We are an enterprise software company.") is False


def test_proxy_reference_disclosures_describe_other_sections() -> None:
    assert is_proxy_reference_disclosure("Portions of Item 1 are incorporated") is True
    assert is_proxy_reference_disclosure("indicate by check mark") is True
    assert is_proxy_reference_disclosure("pursuant to Item 405") is True
    assert is_proxy_reference_disclosure("ITEM 1. BUSINESS") is False


def test_enabled_reads_the_policy_signal_tuple() -> None:
    policy = _policy(BoundarySignal.PAGE_MARKERS)

    assert enabled(policy, BoundarySignal.PAGE_MARKERS) is True
    assert enabled(policy, BoundarySignal.PART_FALLBACK) is False


def test_cover_start_finds_the_first_line_of_the_cover_cluster() -> None:
    result = find_cover_start(
        "\n".join(COVER), _policy(BoundarySignal.COVER_IDENTITY_AND_LAYOUT)
    )

    assert result.start_line == 0
    assert result.start_offset == 0
    assert {item.name for item in result.evidence} == {
        "cover_start_identity",
        "cover_start_shape",
    }


def test_cover_start_is_unknown_without_the_identity_signal() -> None:
    result = find_cover_start("\n".join(COVER), _policy(BoundarySignal.PAGE_MARKERS))

    assert result.start_line is None
    assert result.start_offset is None


def test_cover_start_is_unknown_without_a_policy() -> None:
    assert find_cover_start("\n".join(COVER), None).start_line is None


def test_cover_start_of_an_empty_document_is_unknown() -> None:
    result = find_cover_start("", _policy(BoundarySignal.COVER_IDENTITY_AND_LAYOUT))

    assert result.start_line is None


def test_backward_confirmation_pulls_the_boundary_back_to_the_root() -> None:
    long_prose = (
        "This is a long prose sentence that is well over sixty characters "
        "in length for sure."
    )
    lines = ["PART I", *([long_prose] * 12), "ITEM 1. BUSINESS", "tail"]
    evidence: list[BoundaryEvidence] = []

    adjusted, evidence = confirm_backward_body(lines, len(lines), None, evidence)

    assert adjusted == 0
    assert any(item.name == "backward_body_adjust" for item in evidence)


def test_backward_confirmation_keeps_a_nearby_provisional_end() -> None:
    lines = [
        "PART I",
        "x",
        *[f"filler {index}" for index in range(10)],
        "PART II",
        "ITEM 5. MARKET FOR REGISTRANT\u2019S COMMON EQUITY",
    ]
    evidence: list[BoundaryEvidence] = []

    adjusted, evidence = confirm_backward_body(lines, len(lines), None, evidence)

    assert adjusted == len(lines)
    assert any(item.name == "backward_body_confirm" for item in evidence)


def test_backward_confirmation_of_a_zero_length_document_is_a_no_op() -> None:
    adjusted, evidence = confirm_backward_body([], 0, None, [])

    assert adjusted == 0
    assert evidence == []


def test_boundary_input_accepts_both_text_forms() -> None:
    text = "\n".join(COVER)
    for source in (text, BoundaryInput(text=text)):
        assert (
            find_cover_start(
                source, _policy(BoundarySignal.COVER_IDENTITY_AND_LAYOUT)
            ).start_line
            == 0
        )
