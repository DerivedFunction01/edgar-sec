"""Form-test spec registry: the declared specs for every kind.

Companion to the family-profile registry: profiles declare
which kinds a family carries; the declared entries live in
the form_test_entries modules, composed here in order.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.form_specs.form_signal_specs import (
    FORM_SIGNAL_TEST_ENTRIES,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_entries_composition import (
    COMPOSITION_FORM_TEST_ENTRIES,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_entries_seats import (
    SEAT_FORM_TEST_ENTRIES,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_entries_separators import (
    SEPARATOR_FORM_TEST_ENTRIES,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_entries_statements import (
    STATEMENT_FORM_TEST_ENTRIES,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_types import FormTestSpec
from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    PROV_STEP2_PRICING,
    TEST_LADDER,
)
from edgar_sec.engine.tables.extraction.form_specs.year_ladder_specs import (
    YEAR_LADDER_SPECS,
    YearLadderSpec,
)


__all__ = (
    "FORM_TEST_SPECS",
    "FORM_TEST_SPECS_BY_FAMILY",
    "LADDER_SPECS_BY_TEST_ID",
    "form_test_specs_for",
)


# Form-test specs: every kind's declared specs, per family.
# A walk passes when the table's own beginning balance plus its
# movement rows reconciles to its ending balance within tolerance.
FORM_TEST_SPECS: tuple[FormTestSpec, ...] = (
    *STATEMENT_FORM_TEST_ENTRIES,
    *COMPOSITION_FORM_TEST_ENTRIES,
    *SEPARATOR_FORM_TEST_ENTRIES,
    *SEAT_FORM_TEST_ENTRIES,
    *(
        FormTestSpec(family, kind, test_id, points, provenance=PROV_STEP2_PRICING)
        for family, kind, test_id, points in FORM_SIGNAL_TEST_ENTRIES
    ),
)


# The same parameters keyed by test_id, derived at registry load
# for the stage adapter; never a second literal copy. Ladder-kind
# specs only — other kinds over a ladder family stay out.
LADDER_SPECS_BY_TEST_ID: dict[str, YearLadderSpec] = {
    spec.test_id: YEAR_LADDER_SPECS[spec.family]
    for spec in FORM_TEST_SPECS
    if spec.kind == TEST_LADDER and spec.family in YEAR_LADDER_SPECS
}


FORM_TEST_SPECS_BY_FAMILY: dict[str, tuple[FormTestSpec, ...]] = {}
for _spec in FORM_TEST_SPECS:
    FORM_TEST_SPECS_BY_FAMILY[_spec.family] = (
        *FORM_TEST_SPECS_BY_FAMILY.get(_spec.family, ()),
        _spec,
    )


def form_test_specs_for(family: str) -> tuple[FormTestSpec, ...]:
    """The declared form-test specs for a family; none if undeclared."""
    return FORM_TEST_SPECS_BY_FAMILY.get(family, ())
