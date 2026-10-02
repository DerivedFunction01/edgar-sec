"""Contract tests for the cover data models and enums."""

from __future__ import annotations

import dataclasses

import pytest

from edgar_sec.engine.forms.cover.models import (
    BodyAnchorType,
    BodyRoot,
    BodyStart,
    BodyStartEvidence,
    BoundaryEvidence,
    BoundaryInput,
    BoundaryMethod,
    BoundarySignal,
    CoverBoundary,
    CoverBoundaryPolicy,
    CoverStart,
    DocumentTopology,
)


def test_boundary_signal_values_are_the_profile_capability_vocabulary() -> None:
    assert {signal.value for signal in BoundarySignal} == {
        "cover_identity_and_layout",
        "page_markers",
        "incorporated_reference",
        "toc_transition",
        "part_fallback",
        "amendment_transition",
        "item_fallback",
        "body_prose_fallback",
    }


def test_boundary_method_values_are_the_provenance_vocabulary() -> None:
    assert {method.value for method in BoundaryMethod} == {
        "disabled",
        "marker",
        "structural",
        "phrase",
        "fallback",
        "unknown",
    }


def test_body_anchor_type_covers_every_anchor_kind() -> None:
    assert {anchor.value for anchor in BodyAnchorType} == {
        "structural",
        "semantic",
        "substantive",
        "unknown",
    }


def test_cover_boundary_is_frozen_and_defaults_to_approximate() -> None:
    boundary = CoverBoundary(
        end_line=7,
        end_offset=200,
        method=BoundaryMethod.STRUCTURAL,
        confidence=1.0,
    )

    assert boundary.approximate is True
    assert boundary.evidence == ()
    assert boundary.start_line is None
    with pytest.raises(dataclasses.FrozenInstanceError):
        boundary.end_line = 9  # type: ignore[misc]


def test_boundary_input_defaults_to_ascii_without_page_analysis() -> None:
    assert BoundaryInput(text="PART I").page_analysis is None
    assert BoundaryInput(text="PART I").representation == "ascii"


def test_boundary_policy_defaults_to_no_capabilities() -> None:
    assert CoverBoundaryPolicy().signals == ()


def test_evidence_rows_default_to_empty_details() -> None:
    assert BoundaryEvidence(name="marker", strength=0.5, line=3).details == ""
    assert BodyStartEvidence(name="anchor", strength=0.9, line=4).details == ""


def test_body_root_carries_its_anchor_kind_and_label() -> None:
    root = BodyRoot(line=9, root_type="structural", confidence=0.95, label="PART I")

    assert (root.line, root.root_type, root.confidence, root.label) == (
        9,
        "structural",
        0.95,
        "PART I",
    )


def test_cover_start_unknown_state_is_all_none() -> None:
    assert CoverStart(start_line=None, start_offset=None).evidence == ()


def test_body_start_defaults_to_undelayed_without_rejections() -> None:
    start = BodyStart(
        line=10,
        heading_line=9,
        first_unit_line=11,
        anchor_type=BodyAnchorType.STRUCTURAL.value,
        confidence=0.9,
    )

    assert start.delayed is False
    assert start.rejection_reasons == ()


def test_document_topology_carries_the_four_zone_partition() -> None:
    topology = DocumentTopology(
        cover_start=0,
        cover_end=6,
        toc_start=6,
        toc_end=10,
        body_start=10,
        confidence=0.9,
        method="heading_rows",
    )

    assert (topology.cover_end, topology.toc_end, topology.body_start) == (6, 10, 10)
    assert topology.evidence == ()
