"""Input-class evidence seat: canonical classes over the grid.

Evaluates the seat parameters declared as registry data in
input_class_specs.INPUT_CLASS_EVIDENCE_SPECS; at least
min_classes distinct classes on the grid text seat the family."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.input_class_specs import (
    INPUT_CLASS_EVIDENCE_SPECS,
    InputClassEvidenceSpec,
)


@dataclass(frozen=True, slots=True)
class InputClassText:
    """One geometry's seat text: the grid surface only."""

    grid_text: str = ""

    @classmethod
    def from_geometry(cls, geometry) -> InputClassText:
        """Seat text from a competition GeometryText (duck-typed)."""
        return cls(grid_text=geometry.grid_text)


@dataclass(frozen=True, slots=True)
class InputClassEvidence:
    """The seat verdict for one geometry under one family's spec."""

    admitted: bool
    classes_found: tuple[str, ...]
    detail: str


_REFUSED = InputClassEvidence(False, (), "no input-class spec")


def evaluate_input_class_evidence(
    text: InputClassText, spec: InputClassEvidenceSpec
) -> InputClassEvidence:
    """Evaluate one geometry's grid text against the seat spec."""
    classes = tuple(t for t in spec.input_classes if t in text.grid_text)
    if len(classes) >= spec.min_classes:
        return InputClassEvidence(True, classes, "input classes: " + ", ".join(classes))
    return InputClassEvidence(
        False, classes, f"input classes below {spec.min_classes}: {len(classes)}"
    )


def input_class_evidence_for_geometry(
    geometry, family: str = "valuation_model_assumptions"
) -> InputClassEvidence:
    """The seat verdict for one competition geometry, by family."""
    spec = INPUT_CLASS_EVIDENCE_SPECS.get(family)
    if spec is None:
        return _REFUSED
    return evaluate_input_class_evidence(InputClassText.from_geometry(geometry), spec)


def apply_input_class_seat(
    geometry,
    claims: list[str],
    scores: dict,
    hard_vetoed: dict,
    *,
    floor: float,
    score_type,
    evidence_type,
    family: str = "valuation_model_assumptions",
) -> tuple[list[str], dict]:
    """Seat the family at the floor when the reader admits.
    The claim is appended when absent, the score created or
    lifted; no act when already claimed or hard-vetoed."""
    verdict = input_class_evidence_for_geometry(geometry, family)
    if not verdict.admitted or family in hard_vetoed or family in claims:
        return claims, scores
    existing = scores.get(family)
    if existing is not None and existing.total >= floor:
        return [*claims, family], scores
    base = existing.total if existing is not None else 0.0
    lift = floor - base
    channels = dict(existing.by_channel) if existing is not None else {}
    channels["gate"] = channels.get("gate", 0.0) + lift
    evidence = existing.evidence if existing is not None else ()
    note = evidence_type("gate", verdict.detail, lift)
    seated = score_type(family, floor, channels, evidence + (note,))
    return [*claims, family], {**scores, family: seated}
