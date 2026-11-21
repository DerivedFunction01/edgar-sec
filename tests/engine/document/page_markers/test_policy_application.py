"""Applying a declared page-marker policy to a document."""

from __future__ import annotations

import pytest

from edgar_sec.engine.document.page_markers.artifacts import (
    build_page_artifact_metadata,
)
from edgar_sec.engine.document.page_markers.detector import analyze_page_markers
from edgar_sec.engine.document.page_markers.models import (
    PageArtifactPolicy,
    PageMarkerAction,
    PageMarkerAnalysis,
)
from edgar_sec.engine.document.page_markers.policy import apply_page_markers
from tests.engine.document.page_markers.policy_support import NO_TOC, _paged


def test_an_empty_document_is_returned_unchanged() -> None:
    text, artifacts, templates, next_id = apply_page_markers("")
    assert (text, artifacts, templates, next_id) == ("", (), {}, 1)


def test_sgml_page_tags_are_stripped_with_provenance() -> None:
    text = "<PAGE>\nITEM 1. BUSINESS\n</PAGE>\n"
    result, artifacts, _templates, next_id = apply_page_markers(text)
    assert "<PAGE>" not in result
    assert "ITEM 1. BUSINESS" in result
    assert [artifact.source for artifact in artifacts] == ["sgml-page-tag"] * 2
    assert [artifact.page_number for artifact in artifacts] == [None, None]
    assert all(artifact.removable for artifact in artifacts)
    assert all(artifact.source_identity for artifact in artifacts)
    assert next_id == 3


def test_a_whole_line_removal_takes_its_trailing_newline() -> None:
    result, _artifacts, _templates, _next_id = apply_page_markers(
        "Header\n<PAGE>\nBody\n"
    )
    assert "\n\n" not in result
    assert result.splitlines() == ["Header", "Body"]


def test_preserve_policy_emits_nothing_and_changes_nothing() -> None:
    text = "<PAGE>\nITEM 1. BUSINESS\n</PAGE>\n"
    result, artifacts, templates, next_id = apply_page_markers(
        text, policy=PageArtifactPolicy.PRESERVE
    )
    assert (result, artifacts, templates, next_id) == (text, (), {}, 1)


def test_annotate_policy_replaces_each_span_with_a_token_line() -> None:
    text = "Header\n<PAGE>\nBody\n<PAGE>\n"
    result, artifacts, _templates, next_id = apply_page_markers(
        text, policy=PageArtifactPolicy.ANNOTATE
    )
    assert "[[SEC:PAGE_BREAK id=1]]" in result
    assert "[[SEC:PAGE_BREAK id=2]]" in result
    assert "<PAGE>" not in result
    assert len(artifacts) == 2
    assert next_id == 3


def test_annotate_emits_a_token_for_each_inferred_boundary() -> None:
    text = "\n".join(
        line
        for index in (1, 2, 3, 4, 5, 6, 7)
        for line in (
            ["<PAGE>"]
            + ([str(index), f"Body {index}"] if index in (1, 2, 3, 6, 7) else [])
        )
    )
    analysis = analyze_page_markers(text, NO_TOC)
    assert analysis.inferred_boundaries
    result, artifacts, _templates, _next_id = apply_page_markers(
        text, analysis, PageArtifactPolicy.ANNOTATE
    )
    assert result.count("[[SEC:PAGE_BREAK id=") >= len(analysis.inferred_boundaries)
    inferred = [
        artifact for artifact in artifacts if artifact.source == "inferred-line"
    ]
    assert inferred
    assert all(not artifact.removable for artifact in inferred)
    assert all(artifact.start == artifact.end for artifact in inferred)


def test_an_inferred_boundary_never_emits_a_span() -> None:
    text = "\n".join(
        line
        for index in (1, 2, 3, 4, 5, 6, 7)
        for line in (
            ["<PAGE>"]
            + ([str(index), f"Body {index}"] if index in (1, 2, 3, 6, 7) else [])
        )
    )
    result, artifacts, _templates, _next_id = apply_page_markers(text)
    assert all(
        not (artifact.source == "inferred-line" and artifact.start != artifact.end)
        for artifact in artifacts
    )
    assert "[[SEC:" not in result


def test_an_analysis_for_another_document_is_recomputed() -> None:
    stale = analyze_page_markers("<PAGE>\nA much longer document\n</PAGE>\n")
    text = "<PAGE>\nBody\n</PAGE>\n"
    result, artifacts, _templates, _next_id = apply_page_markers(text, stale)
    assert "<PAGE>" not in result
    assert [artifact.start for artifact in artifacts] == [0, 12]
    assert stale.source_text != text


def test_artifact_ids_are_assigned_in_source_order() -> None:
    text = _paged(4, header="ABC CORP")
    _result, artifacts, _templates, _next_id = apply_page_markers(text)
    sources = [artifact.start for artifact in artifacts]
    assert sources == sorted(sources)
    assert sources == list(dict.fromkeys(sources))


def test_a_marker_starting_an_id_range_resumes_from_the_first_id() -> None:
    text = "<PAGE>\nBody\n</PAGE>\n"
    _result, artifacts, _templates, next_id = apply_page_markers(text, first_id=10)
    assert len(artifacts) == 2
    assert next_id == 12


def test_an_empty_decision_set_leaves_the_document_untouched() -> None:
    text = "Nothing to remove here.\n"
    analysis = PageMarkerAnalysis((), (), (), source_text=text)
    result, artifacts, _templates, next_id = apply_page_markers(text, analysis)
    assert result == text
    assert (artifacts, next_id) == ((), 1)


def test_overlapping_decisions_share_one_rendered_token() -> None:
    # Overlapping decisions merge into one range, so `next_id` counts rendered tokens,
    # not artifacts.
    text = _paged(4, header="ABC CORP")
    _result, artifacts, _templates, next_id = apply_page_markers(text)
    assert len(artifacts) > next_id - 1
    assert len({(item.start, item.end) for item in artifacts}) < len(artifacts) or all(
        item.start < item.end for item in artifacts
    )


def test_sidecar_metadata_is_ordered_for_byte_stable_output() -> None:
    text = _paged(4, header="ABC CORP")
    _result, artifacts, templates, _next_id = apply_page_markers(text)
    first = build_page_artifact_metadata(
        PageArtifactPolicy.STRIP, "src", templates, list(enumerate(artifacts, start=1))
    )
    second = build_page_artifact_metadata(
        PageArtifactPolicy.STRIP,
        "src",
        dict(reversed(list(templates.items()))),
        list(reversed(list(enumerate(artifacts, start=1)))),
    )
    assert first == second
    assert [entry["id"] for entry in first["artifacts"]] == sorted(
        entry["id"] for entry in first["artifacts"]
    )


def test_a_decision_to_preserve_emits_no_artifact() -> None:
    marker = analyze_page_markers("F-3\n", NO_TOC).markers[0]
    analysis = PageMarkerAnalysis(
        (marker,),
        (
            __import__(
                "edgar_sec.engine.document.page_markers.models",
                fromlist=["PageMarkerDecision"],
            ).PageMarkerDecision(
                marker, PageMarkerAction.PRESERVE, "ambiguous_letter_number"
            ),
        ),
        (),
        source_text="F-3\n",
    )
    result, artifacts, _templates, _next_id = apply_page_markers("F-3\n", analysis)
    assert result == "F-3\n"
    assert artifacts == ()


@pytest.mark.parametrize(
    "policy", [PageArtifactPolicy.STRIP, PageArtifactPolicy.ANNOTATE]
)
def test_every_applied_policy_leaves_no_sgml_page_tag(
    policy: PageArtifactPolicy,
) -> None:
    text = _paged(5, header="ABC CORP", footer="Confidential footer")
    result, _artifacts, _templates, _next_id = apply_page_markers(text, policy=policy)
    assert "<PAGE>" not in result
    assert "ABC CORP" not in result
    assert "Confidential footer" not in result
    assert "Body 5" in result
