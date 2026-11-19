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

    foreign_classes names the determined form classes the
    stage refuses here; gold_families names the families
    whose determined own form routes the refusal.
    """

    family: str
    foreign_classes: tuple[str, ...]
    gold_families: tuple[str, ...]
    foreign_shapes: bool
    recast_cell: bool


FORM_SEPARATION_SPECS: dict[str, FormSeparationSpec] = {
    "eps_reconciliation": FormSeparationSpec(
        family="eps_reconciliation",
        foreign_classes=FOREIGN_FORM_CLASSES,
        gold_families=("warrant_activity", "debt_maturity"),
        foreign_shapes=True,
        recast_cell=True,
    ),
    "intangibles": FormSeparationSpec(
        family="intangibles",
        foreign_classes=FOREIGN_FORM_CLASSES,
        gold_families=("inventory",),
        foreign_shapes=False,
        recast_cell=False,
    ),
}
