"""The helper-duplicates scanner: AST body-hash lines and census scope.
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


def test_allows_a_lone_parameterized_get(synthetic_repo: Path) -> None:
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
    assert helper_duplicates.scan_helper_duplicates() == []


def test_flags_duplicated_parameterized_get_bodies(synthetic_repo: Path) -> None:
    inner = '    def fields_of(rep):\n        return rep.get("form_a", {})\n'
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/a.py": (
                "def summarize_a(case_reports):\n"
                + inner
                + "    return fields_of(case_reports[0])\n"
            ),
            "edgar_sec/engine/b.py": (
                "def summarize_b(case_reports):\n"
                + inner
                + "    return [fields_of(case_reports[0])]\n"
            ),
        },
    )
    findings = helper_duplicates.scan_helper_duplicates()
    assert sorted(f.path for f in findings) == [
        "edgar_sec/engine/a.py",
        "edgar_sec/engine/b.py",
    ]
    assert all("is duplicated in" in f.message for f in findings)


def test_allows_the_homes_themselves(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/engine/forms/common/family_scaffold.py": _INT_BODY,
            "edgar_sec/apps/client/operator/operator_kit.py": _INT_BODY,
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


# --- The census scope statement: named clusters are out of cure scope ---


_ADD_COMMON_BODY = (
    "def _add_common(parser):\n"
    '    parser.add_argument("--root", default=".")\n'
    '    parser.add_argument("--verbose", action="store_true")\n'
    "    return parser\n"
)


def test_allows_a_census_scoped_cluster_planted_exactly(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/datasets/cli.py": _ADD_COMMON_BODY,
            "edgar_sec/pipelines/feeds/cli.py": _ADD_COMMON_BODY,
        },
    )
    assert helper_duplicates.scan_helper_duplicates() == []


def test_flags_a_census_scoped_body_at_a_new_site(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/datasets/cli.py": _ADD_COMMON_BODY,
            "edgar_sec/pipelines/feeds/cli.py": _ADD_COMMON_BODY,
            "edgar_sec/pipelines/metadata_sync/flows/cli.py": _ADD_COMMON_BODY,
        },
    )
    findings = helper_duplicates.scan_helper_duplicates()
    assert {f.path for f in findings} == {
        "edgar_sec/pipelines/datasets/cli.py",
        "edgar_sec/pipelines/feeds/cli.py",
        "edgar_sec/pipelines/metadata_sync/flows/cli.py",
    }


def test_allows_the_ruled_keep_cli_main_pair(synthetic_repo: Path) -> None:
    main_body = (
        "def main(argv=None):\n"
        "    args = build_parser().parse_args(argv)\n"
        "    return run(args)\n"
    )
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/datasets/cli.py": main_body,
            "edgar_sec/pipelines/feeds/cli.py": main_body,
        },
    )
    assert helper_duplicates.scan_helper_duplicates() == []
