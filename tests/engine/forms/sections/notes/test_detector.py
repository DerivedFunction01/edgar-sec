"""Tests for financial statement notes sequence detection."""

from __future__ import annotations

from edgar_sec.engine.forms.sections.notes.detector import detect_notes_sequence


def test_detect_monotonic_notes_sequence() -> None:
    text = "\n".join(
        [
            "NOTES TO CONSOLIDATED FINANCIAL STATEMENTS",
            "Note 1. Organization and Summary of Accounting Policies",
            "Accounting policy details.",
            "Note 2. Revenue from Contracts with Customers",
            "Revenue disaggregation tables.",
            "Notes 3 and 4. Debt and Leases",
            "Financing agreements.",
        ]
    )
    seq = detect_notes_sequence(text)
    numbers = [n.note_number for n in seq.notes]
    assert numbers == [1, 2, 3, 4]
    assert seq.anachronistic_rejections == 0


def test_rejects_non_contiguous_note_prose_list() -> None:
    text = "\n".join(
        [
            "NOTES TO FINANCIAL STATEMENTS",
            "Note 1. Summary of Accounting Policies",
            "Details.",
            "refer to Note 2 and Note 7 for accounting details",
            "Note 2. Cash and Equivalents",
            "Cash details.",
        ]
    )
    seq = detect_notes_sequence(text)
    numbers = [n.note_number for n in seq.notes]
    assert numbers == [1, 2]
    assert seq.non_contiguous_rejections >= 1


def test_rejects_backward_note_anachronisms() -> None:
    text = "\n".join(
        [
            "NOTES TO FINANCIAL STATEMENTS",
            "Note 1. Summary of Accounting Policies",
            "Note 5. Debt",
            "As stated in Note 1 earlier.",
            "Note 1.",
            "Note 6. Equity",
        ]
    )
    seq = detect_notes_sequence(text)
    numbers = [n.note_number for n in seq.notes]
    assert numbers == [1, 5, 6]
    assert seq.anachronistic_rejections >= 1
