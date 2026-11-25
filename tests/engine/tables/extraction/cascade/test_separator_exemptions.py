"""S1 separator exemption: a registered family's claim is
spared when every fired rule is in its exempt set."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade.competition import compete
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    FamilyScore,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.form_specs.form_signal_specs import (
    SEPARATOR_EXEMPTIONS,
)
from edgar_sec.engine.tables.extraction.separators.summary_separator import (
    SummarySeparatorResult,
)

CREDIT = "credit_losses_rollforward"


def _run(family: str, rules: tuple[str, ...]):
    geometry = GeometryText(
        stubs=(),
        summary_separator=SummarySeparatorResult(rules=rules),
    )
    scores = {family: FamilyScore(family, 5.0, {"form_test": 3.0, "gate": 2.0}, ())}
    return compete(geometry, scores=scores)


def test_registry_names_credit_and_its_rules() -> None:
    assert CREDIT in SEPARATOR_EXEMPTIONS
    assert "mda_item7_summar_lead" in SEPARATOR_EXEMPTIONS[CREDIT]


def test_sole_fire_within_exempt_set_is_spared() -> None:
    result = _run(CREDIT, ("mda_item7_summar_lead",))
    assert CREDIT in result.claims
    assert any(
        e.channel == "gate" and "exempted" in e.detail
        for e in result.scores[CREDIT].evidence
    )


def test_co_fire_with_non_exempt_rule_still_denied() -> None:
    result = _run(CREDIT, ("mda_item7_summar_lead", "bs_lead"))
    assert CREDIT not in result.claims
    assert any(
        e.channel == "gate" and "summary separator:" in e.detail
        for e in result.scores[CREDIT].evidence
    )


def test_non_registered_family_still_denied() -> None:
    result = _run("pension", ("mda_item7_summar_lead",))
    assert "pension" not in result.claims
