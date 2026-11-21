"""Concept-label preference: each concept's display label, best-ranked first."""

from __future__ import annotations

from collections.abc import Sequence

from edgar_sec.engine.xbrl.schema.models import ConceptLabel

STANDARD_LABEL_ROLE = "http://www.xbrl.org/2003/role/label"


def labels_by_concept(labels: Sequence[ConceptLabel]) -> dict[str, str]:
    best: dict[str, tuple[tuple[int, int], str]] = {}
    for label in labels:
        rank = (
            0 if label.role_uri == STANDARD_LABEL_ROLE else 1,
            0 if label.lang == "en-US" else 1,
        )
        current = best.get(label.concept_qname)
        if current is None or rank < current[0]:
            best[label.concept_qname] = (rank, label.label)
    return {qname: text for qname, (_, text) in best.items()}
