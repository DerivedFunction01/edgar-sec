"""Form-separation specs (TEST_FORM_SEPARATION).

Registry data for the claim-level refusal stage: each
family's foreign form classes and gold-routing families,
as priced by the cascade group 4 board.
"""

from __future__ import annotations

from dataclasses import dataclass

FOREIGN_FORM_CLASSES: tuple[str, ...] = (
    "composition",
    "movement-detail",
    "furniture",
    "percentage-rows",
    "supplemental-schedule",
    "index",
    "summary-columns",
    "ladder-detail",
    "provision-detail",
    "fragment",
    "statement-summary",
)


@dataclass(frozen=True, slots=True)
class FormSeparationSpec:
    """One family's form-separation refusal data.

    foreign_classes names the refused determined form classes;
    gold_families names the families whose own form routes it.
    """

    family: str
    foreign_classes: tuple[str, ...]
    gold_families: tuple[str, ...]
    foreign_shapes: bool
    recast_cell: bool
    segment_detail_cell: bool


FORM_SEPARATION_SPECS: dict[str, FormSeparationSpec] = {
    "eps_reconciliation": FormSeparationSpec(
        family="eps_reconciliation",
        foreign_classes=FOREIGN_FORM_CLASSES,
        gold_families=("warrant_activity", "debt_maturity"),
        foreign_shapes=True,
        recast_cell=True,
        segment_detail_cell=False,
    ),
    "intangibles": FormSeparationSpec(
        family="intangibles",
        foreign_classes=FOREIGN_FORM_CLASSES,
        gold_families=("inventory",),
        foreign_shapes=False,
        recast_cell=False,
        segment_detail_cell=False,
    ),
    # The production-frame board prices this family at F+EXT
    # (register-relatedparty-prodframe.md); the segment-detail
    # cell is the EXT stage, separate from F.
    "related_party": FormSeparationSpec(
        family="related_party",
        foreign_classes=FOREIGN_FORM_CLASSES,
        gold_families=("lease_maturity", "eps_reconciliation"),
        foreign_shapes=False,
        recast_cell=False,
        segment_detail_cell=True,
    ),
}
