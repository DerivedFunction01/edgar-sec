"""Signature-region location, mask/restore, and mangled-name healing.

`SignatureRegion.end_line` is exclusive: the region covers source lines
``start_line`` through ``end_line - 1``, and ``lines`` holds exactly those.
"""

from __future__ import annotations

import pytest

from edgar_sec.engine.document.page_markers.signatures import (
    RE_CONFORMED_SIGNATURE,
    RE_POA_SIGNER,
    find_signature_regions,
    heal_mangled_signature_text,
    is_conformed_signature_line,
    is_signature_label_line,
    mask_signature_regions,
    normalize_signature_marker,
    restore_signature_regions,
    signature_block_has_mangled_text,
)

# --- region location ---------------------------------------------------------


def test_a_document_with_no_signature_has_no_region() -> None:
    assert find_signature_regions(("Just prose.", "And more prose.")) == ()


def test_a_title_header_opens_a_region() -> None:
    lines = ("Name and Title:", "/s/ Jane Doe", "/s/ John Smith")
    (region,) = find_signature_regions(lines)
    assert region.lines == lines
    assert (region.start_line, region.end_line) == (0, 3)
    assert region.signer_count == 2
    assert region.confidence == 0.95


def test_a_continuation_line_needs_a_layout_gap_not_merely_a_title_word() -> None:
    # "Title: President" carries a title keyword but no multi-space or tab gap,
    # so it is not a signature row and stays outside the block. A filing that
    # indents its title lines has them included; one that does not, does not.
    lines = ("Name and Title:", "/s/ Jane Doe", "Title: President")
    (region,) = find_signature_regions(lines)
    assert region.lines == lines[:2]


def test_a_marker_opening_a_region_is_not_counted_as_a_signer() -> None:
    # `signer_count` counts the markers *inside* the region, not the line that
    # opened it. A block whose only conformed marker is its opening line is
    # therefore never returned, because neither a header nor a signer supports
    # it; a second marker inside the block is enough.
    assert find_signature_regions(("/s/ Jane Doe", "  Title: President")) == ()
    (region,) = find_signature_regions(("/s/ One", "/s/ Two"))
    assert region.signer_count == 1
    assert region.confidence == 0.8


def test_an_underline_opens_a_region_that_a_header_also_opens() -> None:
    assert find_signature_regions(("/s/ One", "/s/ Two")) != ()
    (region,) = find_signature_regions(("__________", "/s/ One", "/s/ Two"))
    assert region.confidence == 0.8


def test_blank_lines_between_signers_stay_inside_one_region() -> None:
    (region,) = find_signature_regions(("a", "", "/s/ One", "", "/s/ Two", "", "b"))
    assert (region.start_line, region.end_line) == (2, 5)
    assert region.lines == ("/s/ One", "", "/s/ Two")


def test_body_text_after_a_signature_ends_the_region() -> None:
    lines = ("Name and Title:", "/s/ Jane Doe", "/s/ Two", "", "Body prose again.")
    (region,) = find_signature_regions(lines)
    assert region.end_line == 3
    assert "Body prose again." not in region.lines


def test_two_signers_separated_by_prose_merge_into_one_region() -> None:
    # The scan does not stop at a line it rejects once the region has begun, so
    # every signature-like row that follows is taken as part of the same block.
    # Two signatures with prose between them are therefore one region, and
    # masking it masks the prose too.
    lines = (
        "/s/ One",
        "  Title: President",
        "",
        "  Intervening prose with words",
        "",
        "/s/ Two",
        "  Title: Secretary",
    )
    (region,) = find_signature_regions(lines)
    assert (region.start_line, region.end_line) == (0, len(lines))
    assert region.lines == lines


def test_an_unindented_body_paragraph_splits_two_signature_blocks() -> None:
    lines = (
        "/s/ One",
        "/s/ Two",
        "",
        "Body paragraph.",
        "",
        "Name and Title:",
        "/s/ Three",
    )
    regions = find_signature_regions(lines)
    assert [(item.start_line, item.end_line) for item in regions] == [(0, 2), (5, 7)]


def test_an_indented_body_paragraph_is_absorbed_into_the_block() -> None:
    # An indented alphabetic line following another signature row is a
    # signature row by the same layout-gap rule, so indented prose between two
    # signatures is masked along with them.
    lines = (
        "/s/ One",
        "  Title: President",
        "",
        "  Body prose in columns.",
        "",
        "/s/ Two",
    )
    (region,) = find_signature_regions(lines)
    assert region.lines == lines
    assert region.end_line == len(lines)


def test_a_numeric_date_signals_a_signature_row_only_with_a_gap() -> None:
    assert find_signature_regions(("/s/ Jane", "Date: 1/5/24")) == ()
    (region,) = find_signature_regions(("/s/ One", "  1/5/24", "/s/ Two"))
    assert region.end_line == 3


def test_a_month_and_a_year_signal_a_signature_row_only_with_a_gap() -> None:
    assert find_signature_regions(("/s/ One", "Date: January 5, 2024")) == ()
    (region,) = find_signature_regions(("/s/ One", "  January 5, 2024", "/s/ Two"))
    assert region.end_line == 3


def test_month_with_non_year_numbers_does_not_signal_signature_row() -> None:
    # A prose line containing a month and non-year numbers (e.g. day of month or dollar amount)
    # must not be treated as a signature row.
    lines = (
        "  the registrant as of February 28 was $ 51,611,795.",
        "  As of February 28, the Registrant had outstanding 4,635,884",
    )
    assert find_signature_regions(lines) == ()
    # Even if preceded by an isolated marker, it does not continue the region
    assert find_signature_regions(("/s/ One", *lines, "/s/ Two")) == ()


def test_sec_full_date_signals_signature_row_with_gap() -> None:
    (region,) = find_signature_regions(
        ("/s/ One", "  Dated: March 30, 1998", "/s/ Two")
    )
    assert region.end_line == 3


def test_an_indented_run_with_no_marker_and_no_header_is_not_a_region() -> None:
    assert (
        find_signature_regions(("  Indented one", "  Indented two", "  Indented 3"))
        == ()
    )


def test_a_conformed_marker_needs_only_the_slashes() -> None:
    assert is_conformed_signature_line("/s/ Jane") is True
    assert is_conformed_signature_line("By: /s/ Jane") is True
    assert is_conformed_signature_line("/S/ Jane") is False
    assert is_conformed_signature_line("Jane Doe") is False
    assert RE_CONFORMED_SIGNATURE.match("  /s/") is not None


# --- mask and restore --------------------------------------------------------


def test_masking_without_a_region_is_the_identity() -> None:
    text = "Just prose.\nMore prose.\n"
    assert mask_signature_regions(text) == (text, ())


def test_masking_preserves_the_line_count_and_the_newlines() -> None:
    text = "Name and Title:\n/s/ Jane Doe\n/s/ John Smith\n"
    masked, regions = mask_signature_regions(text)
    assert masked.count("\n") == text.count("\n")
    assert len(masked.splitlines()) == len(text.splitlines())
    assert regions
    assert "__SEC_SIG_" in masked


def test_masking_names_each_token_by_region_and_line_offset() -> None:
    masked, _regions = mask_signature_regions(
        "Name and Title:\n/s/ Jane Doe\n/s/ Two\n"
    )
    assert "__SEC_SIG_0_0__" in masked
    assert "__SEC_SIG_0_1__" in masked
    assert "__SEC_SIG_0_2__" in masked


def test_masking_leaves_text_outside_the_region_untouched() -> None:
    text = "Header\nName and Title:\n/s/ Jane Doe\n/s/ John Smith\n"
    masked, _regions = mask_signature_regions(text)
    assert masked.splitlines()[0] == "Header"


def test_restore_returns_the_exact_original() -> None:
    text = "Name and Title:\n/s/ Jane Doe\n/s/ John Smith\n\nBody.\n"
    masked, regions = mask_signature_regions(text)
    assert masked != text
    assert restore_signature_regions(masked, regions) == text


def test_restore_without_regions_is_the_identity() -> None:
    assert restore_signature_regions("text", ()) == "text"


def test_a_rewritten_masked_line_is_not_undone_by_restore() -> None:
    # The mask is a whole-token replacement, so restore only rewrites the lines
    # that still carry their token. A line whose token was overwritten keeps the
    # overwrite, which is why the mask exists to make an accidental rewrite
    # impossible rather than to make an accidental one reversible.
    text = "Name and Title:\n/s/ Jane Doe\n/s/ John Smith\n"
    masked, regions = mask_signature_regions(text)
    assert restore_signature_regions(masked, regions) == text
    rewritten = masked.replace("__SEC_SIG_0_2__", "rewritten line")
    restored = restore_signature_regions(rewritten, regions)
    assert restored.splitlines() == [
        "Name and Title:",
        "/s/ Jane Doe",
        "rewritten line",
    ]


def test_two_identical_regions_are_restored_independently() -> None:
    text = (
        "Name and Title:\n/s/ One\n  Title: President\n"
        "Body paragraph between the two blocks.\n"
        "Name and Title:\n/s/ Two\n  Title: President"
    )
    masked, regions = mask_signature_regions(text)
    assert len(regions) == 2
    assert restore_signature_regions(masked, regions) == text


# --- marker normalization ----------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/s/ Jane Doe", "/s/ Jane Doe"),
        ("/S/ JANE DOE", "/s/ JANE DOE"),
        ("/ S / S ATYA N ADELLA", "/s/ S ATYA N ADELLA"),
        ("/ s / s atya n adella", "/s/ s atya n adella"),
        ("/s/", "/s/"),
        ("Jane Doe", "Jane Doe"),
    ],
)
def test_a_signature_marker_is_canonicalized(text: str, expected: str) -> None:
    assert normalize_signature_marker(text) == expected


# --- mangled names -----------------------------------------------------------


def test_a_mangled_marker_and_name_is_confirmed() -> None:
    assert signature_block_has_mangled_text(("/ S / S ATYA N ADELLA",)) is True
    assert signature_block_has_mangled_text(("/s/ A LICE L. J OLLA",)) is True
    assert signature_block_has_mangled_text(("/s/ Jane Doe",)) is False
    assert signature_block_has_mangled_text(()) is False


def test_healing_collapses_only_isolated_single_letter_gaps() -> None:
    assert heal_mangled_signature_text("/s/ S ATYA N ADELLA") == "/s/ SATYA NADELLA"
    assert heal_mangled_signature_text("/ S / S ATYA N ADELLA") == "/s/ SATYA NADELLA"


def test_an_initial_with_its_period_keeps_its_spacing() -> None:
    # `L.` is not an isolated single letter, so the gap after it is left alone.
    assert heal_mangled_signature_text("/s/ A LICE L. J OLLA") == "/s/ ALICE L. JOLLA"


def test_healing_canonicalizes_the_marker_without_touching_the_case() -> None:
    assert heal_mangled_signature_text("/S/ Jane Doe") == "/s/ Jane Doe"


def test_text_outside_a_confirmed_mangled_block_is_left_alone() -> None:
    assert heal_mangled_signature_text("ALPHA BETA GAMMA DELTA") == (
        "ALPHA BETA GAMMA DELTA"
    )


def test_healing_leaves_a_lowercase_continuation_alone() -> None:
    assert heal_mangled_signature_text("/s/ Jane Doe") == "/s/ Jane Doe"


# --- attorney-in-fact & asterisk signatures ---------------------------------


def test_poa_with_asterisk_and_attorney_in_fact_is_recognized() -> None:
    lines = (
        "               *",
        "--------------------------------------------",
        "Christopher J. Schaepe                        Director",
        "",
        "*By: /s/ Dr. Zaki Rakib",
        "    ----------------------------------------",
        "     Dr. Zaki Rakib",
        "     Attorney-In Fact",
    )
    (region,) = find_signature_regions(lines)
    assert region.start_line == 0
    assert region.end_line == 8
    assert region.signer_count == 1


def test_conformed_signature_with_variable_spacing() -> None:
    assert is_conformed_signature_line("By: /s/ John Doe") is True
    assert is_conformed_signature_line("By: / s / John Doe") is True
    assert is_conformed_signature_line("*By: /s/ John Doe") is True
    assert is_conformed_signature_line("* By /s/ John Doe") is True
    assert is_conformed_signature_line("By: /S/ John Doe") is False
    assert is_conformed_signature_line("* By /S/ John Doe") is False


def test_poa_signer_without_slash_s() -> None:
    lines = (
        "               *",
        "--------------------------------------------",
        "Christopher J. Schaepe                        Director",
        "",
        "*By: Jane Doe",
        "     Attorney-in-Fact",
    )
    (region,) = find_signature_regions(lines)
    assert region.start_line == 0
    assert region.end_line == 6
    assert region.signer_count == 1


def test_is_signature_label_line_with_asterisk_by() -> None:
    assert is_signature_label_line("*By: Jane Doe") is True
    assert is_signature_label_line("* By: Jane Doe") is True


def test_is_conformed_signature_line_with_poa_signer() -> None:
    assert bool(RE_POA_SIGNER.match("*By: Jane Doe")) is True
    assert is_conformed_signature_line("*By: Jane Doe, Attorney-in-Fact") is True
    assert is_conformed_signature_line("*By: Jane Doe") is True
    assert is_conformed_signature_line("* By: (Bruce M. Gack)") is True
