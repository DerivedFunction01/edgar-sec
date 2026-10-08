"""The operator wizard as a presentation layer over the CLI: exposed actions,
delegation, and discovery in place of typed identifiers.
"""

from __future__ import annotations

import argparse
from typing import Any

import pytest

from edgar_sec.engine.selection.policy import SelectionPolicy
from edgar_sec.pipelines.filing_catalog import cli, operator
from edgar_sec.pipelines.filing_catalog.operator import (
    MENU_TITLE,
    build_operator_menu,
    main,
)
from edgar_sec.pipelines.filing_catalog.paths import resolve_filing_catalog_paths

# --- the menu --------------------------------------------------------------


# One discovered draft in the shape `discover_policies` returns.
_DRAFT: dict[str, Any] = {
    "path": "/artifacts/filing_catalog/policies/draft.json",
    "name": "draft.json",
    "corpus_id": "corpus_deadbeef",
    "forms": ["10-K", "8-K"],
    "level": 1,
    "base_content_units": 400,
    "policy_fingerprint": "0" * 32,
    "seed_cik_path": "__absent__",
    "date_selection_text": "@Q1",
    "derives_era_bands": True,
    "era_band_count": 0,
}


def _stub_auto_policy(catalog: str, paths: Any = None) -> SelectionPolicy:
    """A policy that needs no catalog, so draft writing is testable offline."""
    return SelectionPolicy(
        corpus_id=f"corpus_{catalog}",
        forms=["10-K"],
        base_content_units=100,
        seed_cik_path="__absent__",
    )


def test_the_menu_exposes_every_command_an_operator_can_drive() -> None:
    labels = [action.label.lower() for action in build_operator_menu()]
    assert any("report" in label for label in labels)
    assert any("materialize" in label or "dag" in label for label in labels)
    assert any("catalog" in label and "plan" in label for label in labels)
    assert any("selection policy" in label for label in labels)
    assert any("expand" in label for label in labels)


def test_every_cli_subcommand_is_reachable_one_way_or_the_other() -> None:
    """A command with no menu entry and no documented reason is dead surface."""
    menu = " ".join(
        (action.label + " " + action.callback.__name__).lower()
        for action in build_operator_menu()
    )
    for command in ("materialize", "plan", "expand", "status"):
        assert command in menu, command


def test_every_action_is_callable() -> None:
    for action in build_operator_menu():
        assert callable(action.callback)


# --- delegation ------------------------------------------------------------


def test_actions_delegate_to_the_cli_commands() -> None:
    """The wizard must not reimplement behaviour the CLI already owns."""
    for action in build_operator_menu():
        assert action.callback.__module__ == operator.__name__
    assert operator.cmd_status is cli.cmd_status
    assert operator.cmd_plan is cli.cmd_plan
    assert operator.cmd_materialize is cli.cmd_materialize
    assert operator.cmd_expand is cli.cmd_expand


def test_a_supplied_command_bypasses_the_menu(monkeypatch: pytest.MonkeyPatch) -> None:
    """With a command on argv the operator is the CLI, not a prompt."""
    calls: list[list[str]] = []
    monkeypatch.setattr(operator, "cli_main", lambda argv: calls.append(argv) or 0)
    assert main(["status"]) == 0
    assert calls == [["status"]]


def test_the_menu_title_names_the_phase() -> None:
    assert "Filing Catalog" in MENU_TITLE


# --- prompt plumbing -------------------------------------------------------


def test_namespace_carries_every_field_the_commands_read() -> None:
    """A missing attribute must not surface as AttributeError at the prompt."""
    namespace = operator._namespace("plan", catalog="current", forms="10-K 8-K")
    assert isinstance(namespace, argparse.Namespace)
    assert namespace.command == "plan"
    assert namespace.forms == ["10-K", "8-K"]
    for field in ("scope", "suffixes", "limit", "artifacts"):
        assert hasattr(namespace, field), f"cmd_plan reads {field}"
    for field in ("source", "source_manifest"):
        assert hasattr(namespace, field), f"cmd_materialize reads {field}"
    for field in ("parent_plan", "target_units"):
        assert hasattr(namespace, field), f"cmd_expand reads {field}"


def test_a_blank_forms_prompt_means_no_filter() -> None:
    assert operator._namespace("plan", forms="").forms == []
    assert operator._namespace("plan", forms="  ").forms == []


def test_comma_and_space_separated_forms_agree() -> None:
    assert operator._namespace("plan", forms="10-K,8-K").forms == ["10-K", "8-K"]
    assert operator._namespace("plan", forms="10-K, 8-K").forms == ["10-K", "8-K"]


def test_a_blank_dates_prompt_is_the_empty_selection() -> None:
    """Blank is an answer, not a skipped question: it means no date predicate."""
    assert operator._namespace("plan", dates="").dates == ""


def test_the_dates_prompt_returns_what_the_operator_typed() -> None:
    answers = iter([" @Q1[1999..2001] , 2024 "])

    def _prompt(prompt: str, default: str) -> str:
        return next(answers)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(operator, "prompt_text", _prompt)
        assert operator._ask_dates() == "@Q1[1999..2001] , 2024"


@pytest.mark.parametrize("rejected", ["2024Q5", "Q1", "@M13", ".."])
def test_the_dates_prompt_re_asks_until_the_selection_parses(
    rejected: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """A second grammar would drift from the planner the answers reach."""
    answers = iter([rejected, "@Q1"])
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(operator, "prompt_text", lambda prompt, default: next(answers))
        assert operator._ask_dates() == "@Q1"
    assert "invalid date selection" in capsys.readouterr().out


def test_every_prompted_action_builds_a_usable_namespace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Drive each action with scripted answers and a stubbed command."""
    seen: list[argparse.Namespace] = []

    def _capture(args: argparse.Namespace) -> int:
        seen.append(args)
        return 0

    # In menu order; the counts are why each action's answers appear where they do.
    answers = iter(["cat-1", "10-K", "@Q1[1999..2001]", "cat-2", "1", "1", "5000"])
    monkeypatch.setattr(operator, "prompt_text", lambda prompt, default: next(answers))
    monkeypatch.setattr(operator, "discover_catalogs", lambda _paths: [])
    monkeypatch.setattr(operator, "discover_policies", lambda _paths: [_DRAFT])
    monkeypatch.setattr(
        operator,
        "discover_plans",
        lambda _paths: [
            {"plan_id": "plan-1", "scope": "policy", "unique_locators_count": 100}
        ],
    )
    for name in ("cmd_status", "cmd_plan", "cmd_materialize", "cmd_expand"):
        monkeypatch.setattr(operator, name, _capture)

    for action in build_operator_menu():
        action.callback()

    assert [namespace.command for namespace in seen] == [
        "status",
        "plan",
        "plan",
        "expand",
    ]
    plan_namespace = seen[1]
    assert plan_namespace.catalog == "cat-1"
    assert plan_namespace.forms == ["10-K"]
    assert plan_namespace.dates == "@Q1[1999..2001]"
    assert plan_namespace.scope == "deterministic"

    policy_namespace = seen[2]
    assert policy_namespace.catalog == "cat-2"
    assert policy_namespace.scope == "policy"
    assert policy_namespace.policy == _DRAFT["path"]


def test_no_action_ever_asks_for_the_artifacts_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """A per-action root prompt duplicates the registered setting's authority."""
    asked: list[str] = []
    seen: list[argparse.Namespace] = []

    def _record(label: str, default: str = "") -> str:
        asked.append(label)
        if "rtifact" in label:
            pytest.fail(f"the menu asked for the artifacts root: {label!r}")
        return default

    monkeypatch.setattr(operator, "prompt_text", _record)
    monkeypatch.setattr(operator, "discover_catalogs", lambda _paths: [])
    monkeypatch.setattr(operator, "discover_policies", lambda _paths: [_DRAFT])
    monkeypatch.setattr(
        operator,
        "discover_plans",
        lambda _paths: [
            {"plan_id": "plan-1", "scope": "policy", "unique_locators_count": 100}
        ],
    )
    monkeypatch.setattr(
        operator, "resolve_filing_catalog_paths", lambda root=None: _paths(tmp_path)
    )
    monkeypatch.setattr(operator, "auto_policy", _stub_auto_policy)
    for name in ("cmd_status", "cmd_plan", "cmd_materialize", "cmd_expand"):
        monkeypatch.setattr(operator, name, lambda args: seen.append(args) or 0)

    for action in build_operator_menu():
        action.callback()

    # The policy action answers blank, which is its write-a-new-draft path.
    assert [namespace.command for namespace in seen] == [
        "status",
        "plan",
        "expand",
    ]
    assert all(namespace.artifacts == "" for namespace in seen)
    assert asked, "the actions must still prompt for their own inputs"


# --- the policy-plan action -------------------------------------------------


def _policy_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Any:
    paths = resolve_filing_catalog_paths(tmp_path)
    monkeypatch.setattr(
        operator, "resolve_filing_catalog_paths", lambda root=None: paths
    )
    monkeypatch.setattr(operator, "discover_catalogs", lambda _paths: [])
    return paths


def test_a_blank_draft_choice_writes_a_draft_and_plans_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: Any
) -> None:
    """Auto-selecting a draft would publish a plan the operator never chose."""
    paths = _policy_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(operator, "discover_policies", lambda _paths: [_DRAFT])
    monkeypatch.setattr(operator, "auto_policy", _stub_auto_policy)
    monkeypatch.setattr(operator, "prompt_text", lambda prompt, default: "")
    planned: list[argparse.Namespace] = []
    monkeypatch.setattr(operator, "cmd_plan", lambda args: planned.append(args) or 0)

    operator._action_plan_policy()

    assert planned == []
    written = list(paths.policies_root.glob("*.json"))
    assert len(written) == 1
    reloaded = SelectionPolicy.from_path(written[0])
    assert reloaded.forms == ["10-K"]
    assert reloaded.date_selection == []
    assert reloaded.derives_era_bands
    assert str(written[0]) in capsys.readouterr().out


def test_choosing_a_draft_by_number_plans_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    _policy_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(operator, "discover_policies", lambda _paths: [_DRAFT])
    monkeypatch.setattr(operator, "auto_policy", _stub_auto_policy)
    monkeypatch.setattr(operator, "prompt_text", lambda prompt, default: "1")
    planned: list[argparse.Namespace] = []
    monkeypatch.setattr(operator, "cmd_plan", lambda args: planned.append(args) or 0)

    operator._action_plan_policy()

    assert len(planned) == 1
    assert planned[0].scope == "policy"
    assert planned[0].policy == _DRAFT["path"]


def test_a_draft_choice_outside_the_list_is_re_asked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: Any
) -> None:
    """A mistyped number must not fall through to "write a new draft"."""
    _policy_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(operator, "discover_policies", lambda _paths: [_DRAFT])
    monkeypatch.setattr(operator, "auto_policy", _stub_auto_policy)
    answers = iter(["0", "nope", "2", "1"])
    monkeypatch.setattr(operator, "prompt_text", lambda prompt, default: next(answers))
    planned: list[argparse.Namespace] = []
    monkeypatch.setattr(operator, "cmd_plan", lambda args: planned.append(args) or 0)

    operator._action_plan_policy()

    assert len(planned) == 1
    assert "enter a number between 1 and 1" in capsys.readouterr().out


def test_the_policy_action_reports_when_there_are_no_drafts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: Any
) -> None:
    _policy_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(operator, "discover_policies", lambda _paths: [])
    monkeypatch.setattr(operator, "auto_policy", _stub_auto_policy)
    monkeypatch.setattr(operator, "prompt_text", lambda prompt, default: "")
    monkeypatch.setattr(operator, "cmd_plan", lambda _args: pytest.fail("planned"))

    operator._action_plan_policy()

    assert "no policy drafts found" in capsys.readouterr().out


def test_a_draft_name_that_is_not_a_safe_identifier_is_refused(
    tmp_path: Any,
) -> None:
    """The draft name becomes a filename, so it is reduced, not trusted."""
    paths = resolve_filing_catalog_paths(tmp_path)
    with pytest.raises(ValueError, match="must reduce to"):
        operator._draft_path(paths, "../../escape")
    assert operator._draft_path(paths, "Quarterly 8-K").name == "quarterly-8-k.json"


# --- discovery -------------------------------------------------------------


def test_expand_resolves_a_picked_parent_to_its_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """The plan directory is resolved from the pick, never typed by the operator."""
    seen: list[argparse.Namespace] = []
    monkeypatch.setattr(operator, "prompt_text", lambda prompt, default: default)
    monkeypatch.setattr(
        operator,
        "discover_plans",
        lambda _paths: [
            {"plan_id": "plan-1", "scope": "policy", "unique_locators_count": 100},
            {"plan_id": "plan-2", "scope": "deterministic", "unique_locators_count": 5},
        ],
    )
    monkeypatch.setattr(operator, "cmd_expand", lambda args: seen.append(args) or 0)
    monkeypatch.setattr(
        operator, "resolve_filing_catalog_paths", lambda root=None: _paths(tmp_path)
    )

    operator._action_expand()

    assert len(seen) == 1
    assert seen[0].parent_plan == str(_paths(tmp_path).plan_dir("plan-1"))
    assert seen[0].target_units == 100


def test_expand_never_offers_a_plan_it_would_refuse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys
) -> None:
    """Expansion refuses a deterministic parent, so listing one is a dead choice."""
    monkeypatch.setattr(operator, "prompt_text", lambda prompt, default: default)
    monkeypatch.setattr(
        operator,
        "discover_plans",
        lambda _paths: [{"plan_id": "plan-2", "scope": "deterministic"}],
    )
    monkeypatch.setattr(operator, "cmd_expand", lambda args: pytest.fail("expanded"))
    monkeypatch.setattr(
        operator, "resolve_filing_catalog_paths", lambda root=None: _paths(tmp_path)
    )

    operator._action_expand()
    assert "no policy-driven plan" in capsys.readouterr().out


def test_expand_refuses_a_contraction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys
) -> None:
    """A smaller target is a contraction; the command refuses it, so the menu does."""
    monkeypatch.setattr(
        operator, "resolve_filing_catalog_paths", lambda root=None: _paths(tmp_path)
    )
    monkeypatch.setattr(
        operator,
        "discover_plans",
        lambda _paths: [
            {"plan_id": "plan-1", "scope": "policy", "unique_locators_count": 900}
        ],
    )
    monkeypatch.setattr(operator, "cmd_expand", lambda args: pytest.fail("expanded"))

    def answers(prompt: str, default: str = "") -> str:
        if "Parent plan" in prompt:
            return "1"
        return "10"

    monkeypatch.setattr(operator, "prompt_text", answers)

    operator._action_expand()
    assert "contraction" in capsys.readouterr().out


def test_catalog_selection_prefers_the_published_pointer(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """A blank answer keeps ``current``; the listing makes the alternative visible."""
    monkeypatch.setattr(
        operator,
        "discover_catalogs",
        lambda _paths: [
            {"catalog_id": "cat-a", "target_row_count": 10, "part_count": 1},
            {"catalog_id": "cat-b", "target_row_count": 20, "part_count": 2},
        ],
    )
    monkeypatch.setattr(operator, "current_catalog_id", lambda _paths: "cat-b")
    monkeypatch.setattr(operator, "prompt_text", lambda prompt, default: default)

    assert operator._ask_catalog() == "cat-b"
    out = capsys.readouterr().out
    assert "cat-a" in out and "cat-b [current]" in out
    assert "20,000" not in out


def test_a_catalog_can_still_be_chosen_by_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        operator,
        "discover_catalogs",
        lambda _paths: [
            {"catalog_id": "cat-a", "target_row_count": 10, "part_count": 1},
            {"catalog_id": "cat-b", "target_row_count": 20, "part_count": 2},
        ],
    )
    monkeypatch.setattr(operator, "current_catalog_id", lambda _paths: "cat-b")
    monkeypatch.setattr(operator, "prompt_text", lambda prompt, default: "1")
    assert operator._ask_catalog() == "cat-a"


def test_an_invalid_catalog_number_falls_back_to_current(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(
        operator,
        "discover_catalogs",
        lambda _paths: [
            {"catalog_id": "cat-a", "target_row_count": 1, "part_count": 1}
        ],
    )
    monkeypatch.setattr(operator, "current_catalog_id", lambda _paths: "cat-a")
    monkeypatch.setattr(operator, "prompt_text", lambda prompt, default: "nope")
    assert operator._ask_catalog() == "current"
    assert "invalid selection" in capsys.readouterr().out


def test_no_catalogs_published_falls_back_to_the_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(operator, "discover_catalogs", lambda _paths: [])
    monkeypatch.setattr(operator, "prompt_text", lambda prompt, default: default)
    assert operator._ask_catalog() == "current"


def _paths(tmp_path: Any):
    from edgar_sec.pipelines.filing_catalog.paths import resolve_filing_catalog_paths

    return resolve_filing_catalog_paths(tmp_path)
