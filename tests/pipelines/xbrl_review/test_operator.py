"""Tests for XBRL review operator console and menus."""

from edgar_sec.pipelines.xbrl_review.operator import build_operator_menu, main


def test_build_operator_menu() -> None:
    """Verify operator menu actions are built correctly."""
    actions = build_operator_menu()
    labels = [a.label for a in actions]
    assert any("benchmark" in l.lower() for l in labels)
    assert any("review run" in l.lower() for l in labels)
    assert any("compare" in l.lower() for l in labels)
    assert any("promote" in l.lower() for l in labels)


def test_operator_main_delegates_to_cli() -> None:
    """Verify operator entrypoint forwards non-empty argv to CLI."""
    exit_code = main(["--help"])
    assert exit_code == 0
