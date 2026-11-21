"""Operator: the menu binds the same commands the CLI exposes."""

from __future__ import annotations

from edgar_sec.pipelines.datasets.operator import WizardState, build_operator_menu


def test_menu_has_population_verify_and_status() -> None:
    labels = [action.label for action in build_operator_menu(WizardState())]
    assert labels == [
        "Load BDC population register",
        "Verify store (oracle pass)",
        "Store status",
    ]
