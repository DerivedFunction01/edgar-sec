"""The helper-duplicates scanner: AST body-hash and parameterized-get lines.
A copied helper body drifts in one module and not the other; the negatives
pin the shapes that legitimately repeat: unlike bodies and trivial getters.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.scanners import helper_duplicates


def _build_repo(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@pytest.fixture()
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


_INT_BODY = (
    "def _int(elem):\n"
    "    txt = xml_element_text_or_none(elem)\n"
    "    if not txt:\n"
    "        return None\n"
    "    try:\n"
    "        return int(txt.replace(',', ''))\n"
    "    except ValueError:\n"
    "        return None\n"
)


# --- The body-hash line: positives are the production copies verbatim ---


def test_flags_identical_bodies_across_modules(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/a.py": _INT_BODY,
            "edgar_sec/engine/b.py": _INT_BODY,
        },
    )
    findings = helper_duplicates.scan_helper_duplicates()
    assert {f.path for f in findings} == {
        "edgar_sec/engine/a.py",
        "edgar_sec/engine/b.py",
    }


def test_flags_a_copy_of_a_home_body(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/forms/common/family_scaffold.py": (
                "def element_int(elem):\n" + _INT_BODY.split("\n", 1)[1]
            ),
            "edgar_sec/engine/a.py": _INT_BODY,
        },
    )
    findings = helper_duplicates.scan_helper_duplicates()
    assert [f.path for f in findings] == ["edgar_sec/engine/a.py"]
    assert "duplicates its home" in findings[0].message


def test_flags_nested_parameterized_get(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/a.py": (
                "def summarize(case_reports):\n"
                "    def fields_of(rep):\n"
                '        return rep.get("form_a", {})\n'
                "    return fields_of(case_reports[0])\n"
            )
        },
    )
    findings = helper_duplicates.scan_helper_duplicates()
    assert len(findings) == 1
    assert "parameterized get" in findings[0].message


def test_allows_the_homes_themselves(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/forms/common/family_scaffold.py": _INT_BODY,
            "edgar_sec/apps/client/operator_kit.py": _INT_BODY,
        },
    )
    assert helper_duplicates.scan_helper_duplicates() == []


# --- Negatives: shapes the rule is scoped to allow ---


def test_allows_same_name_different_bodies(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/a.py": (
                "def _normalize_form(token):\n    return token.strip().upper()\n"
            ),
            "edgar_sec/engine/b.py": (
                "def _normalize_form(value):\n"
                '    normalized = " ".join(value.split()).upper()\n'
                "    return resolve_alias(normalized) or normalized\n"
            ),
        },
    )
    assert helper_duplicates.scan_helper_duplicates() == []


def test_allows_trivial_one_line_getters(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/a.py": "def _name(node):\n    return node.name\n",
            "edgar_sec/engine/b.py": "def _name(node):\n    return node.name\n",
        },
    )
    assert helper_duplicates.scan_helper_duplicates() == []


def test_allows_identical_methods(synthetic_repo: Path) -> None:
    body = (
        "class Lock:\n"
        "    def __exit__(self, *exc):\n"
        "        self.close()\n"
        "        return False\n"
    )
    _build_repo(
        synthetic_repo,
        {"edgar_sec/engine/a.py": body, "edgar_sec/engine/b.py": body},
    )
    assert helper_duplicates.scan_helper_duplicates() == []


def test_allows_import_alias_of_a_home_helper(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/forms/common/family_scaffold.py": (
                "def element_int(elem):\n" + _INT_BODY.split("\n", 1)[1]
            ),
            "edgar_sec/engine/a.py": (
                "from edgar_sec.engine.forms.common.family_scaffold import (\n"
                "    element_int as _int,\n"
                ")\n"
            ),
        },
    )
    assert helper_duplicates.scan_helper_duplicates() == []
