"""Note-title families: residual clusters whose home is a note title.

Seeded by the Step 8c note census over the derivation residual pool
and confirmed by the context drive; the note's identity is the
family's evidence — no companion label term covers the clusters.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.registry import NoteTitleSpec

NOTE_TITLE_SPECS: tuple[NoteTitleSpec, ...] = (
    NoteTitleSpec("subsequent_events", "subsequent event", 5.0, 0.957, 633),
    NoteTitleSpec("segment_reporting", "segment", 5.0, 0.921, 449),
    NoteTitleSpec(
        "commitments_contingencies", "commitments and contingencies", 5.0, 0.989, 117
    ),
    NoteTitleSpec("related_party", "related party", 5.0, 0.950, 63),
)
NOTE_TITLES_BY_FAMILY = {spec.family: spec for spec in NOTE_TITLE_SPECS}
