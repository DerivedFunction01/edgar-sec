"""Combined operations separator parameter table (TEST_COMBINED_OPERATIONS_SEPARATOR).
The priced claim-local legs as data: S1 rows, S2 numeric share,
S3 period span, C1 typed-core completeness, over the family's
own candidate set (corefin COCI cascade pricing).
"""

from __future__ import annotations

from dataclasses import dataclass

MEASURE_SET_TEST_ID = "combined_operations_ci_measure_set"
JOINT_MEASURE_SET_TEST_ID = "combined_operations_ci_joint_measure_set"

# The typed core's measure groups, by index into the measure-set
# spec's group tuple: descent, terminus, comprehensive total.
# The OCI group is supporting evidence, never a core member.
CORE_GROUP_INDICES = (0, 1, 3)


@dataclass(frozen=True, slots=True)
class CombinedOperationsSeparatorSpec:
    """One family's priced cascade thresholds.

    max_rows: S1 fires at or below this count; numeric_share_bound: S2 fires
    strictly below this share; min_year_columns: S3 fires at or above it.
    """

    family: str
    max_rows: int
    numeric_share_bound: float
    min_year_columns: int


# Location refusals: a combined statement reproduced as a segment-note
# allocation or comparative-figures restatement is not the family's
# statement. (field, phrase) pairs over the geometry's text context.
LOCATION_REFUSALS: tuple[tuple[str, str], ...] = (
    ("notehead", "segmented information"),
    ("notehead", "segment information"),
    ("notehead", "comparative figures"),
    ("lead_title", "allocation of the statements of operations"),
    ("leadin", "allocation of the statements of operations"),
)

COMBINED_OPERATIONS_SEPARATOR_SPECS: dict[str, CombinedOperationsSeparatorSpec] = {
    "combined_operations_ci": CombinedOperationsSeparatorSpec(
        family="combined_operations_ci",
        max_rows=8,
        numeric_share_bound=0.3,
        min_year_columns=5,
    ),
}
