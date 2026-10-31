"""The legacy-shims scanner.
An alias always looks like prudence when it is added, so the tests cover the
identifier forms, the comment forms, and the exemptions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.scanners import legacy_shims


def _build_repo(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@pytest.fixture()
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_flags_underscore_prefixed_legacy_function(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": "def _legacy_build_rows() -> None:\n    pass\n"},
    )
    findings = legacy_shims.scan_legacy_shims()
    assert [f.path for f in findings] == ["edgar_sec/engine/thing.py"]


def test_flags_compat_alias_assignment(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": "compat_old = new_name\n"},
    )
    assert legacy_shims.scan_legacy_shims()


def test_flags_compat_class(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": "class LegacyThing:\n    pass\n"},
    )
    assert legacy_shims.scan_legacy_shims()


def test_flags_bare_class_alias(synthetic_repo: Path) -> None:
    """``Alias = Real`` is the §1.1 form that reads like taste, and a previous
    revision of this scanner missed it entirely.
    """
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/foundation/runtime/resources.py": (
                "SystemResources = RuntimeResourceProfile\n"
            )
        },
    )
    findings = legacy_shims.scan_legacy_shims()
    assert findings
    assert "SystemResources" in findings[0].message


def test_alias_to_itself_is_not_a_shim(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": "Result = Result\n"},
    )
    assert legacy_shims.scan_legacy_shims() == []


def test_module_attribute_and_type_aliases_are_not_flagged(
    synthetic_repo: Path,
) -> None:
    """``Foo = bar.Foo`` re-exports; ``Vector = list[float]`` is structural."""
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                "Foo = bar.Foo\nVector = list[float]\nLOWER = 'x'\n"
            )
        },
    )
    assert legacy_shims.scan_legacy_shims() == []


def test_flags_compatibility_comment(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": "# kept for compatibility with v1\nx = 1\n"},
    )
    assert legacy_shims.scan_legacy_shims()


def test_allows_unrelated_identifier(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": "def build_rows() -> None:\n    pass\n"},
    )
    assert legacy_shims.scan_legacy_shims() == []


def test_ignores_entrypoints(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "check.py": "def _legacy_helper() -> None:\n    pass\n",
            "run.py": "compat_entry = 1\n",
        },
    )
    assert legacy_shims.scan_legacy_shims() == []


def test_ignores_scanner_tests(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "tests/foundation/scanners/test_custom.py": "def _legacy_helper() -> None:\n    pass\n"
        },
    )
    assert legacy_shims.scan_legacy_shims() == []


def test_flags_test_files_with_legacy_shims(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "tests/infra/test_thing.py": "def test_legacy_behavior() -> None:\n    pass\n"
        },
    )
    assert legacy_shims.scan_legacy_shims()


def test_flags_unanchored_phrasing_in_comment_and_docstring(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/thing.py": (
                "# Also check legacy directories\n"
                "def foo() -> None:\n"
                '    """This is deprecated."""\n'
            )
        },
    )
    assert len(legacy_shims.scan_legacy_shims()) == 2


def test_hint_cites_the_agents_rule(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/thing.py": "def _legacy_build_rows() -> None:\n    pass\n"},
    )
    assert "AGENTS.md" in legacy_shims.scan_legacy_shims()[0].hint
