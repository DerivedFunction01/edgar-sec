"""Policy scanner behaviour.
A scanner that silently stops matching is as damaging as a broken contract, so
these build a synthetic tree and assert each scanner’s verdict.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.scanners import (
    clean_exit,
    environment,
    layers,
    length,
    paths,
)
from edgar_sec.foundation.scanners import secrets as secrets_scanner


def _build_repo(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@pytest.fixture()
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a throwaway repository tree and make it the scanner's cwd."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_clean_exit_flags_sys_exit_in_library_function(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/domain/models.py": (
                "import sys\n\n\ndef bail() -> None:\n    sys.exit(2)\n"
            )
        },
    )
    findings = clean_exit.scan_clean_exit()
    assert [f.path for f in findings] == ["edgar_sec/domain/models.py"]


def test_clean_exit_flags_sys_exit_without_entrypoint_guard(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/domain/models.py": "import sys\n\nsys.exit(1)\n"},
    )
    assert clean_exit.scan_clean_exit()


def test_clean_exit_allows_exit_confined_to_entrypoint_guard(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/tool.py": (
                "import sys\n\n\ndef main() -> int:\n    return 0\n\n\n"
                'if __name__ == "__main__":\n    sys.exit(main())\n'
            )
        },
    )
    assert clean_exit.scan_clean_exit() == []


def test_clean_exit_allows_cli_and_operator_entrypoints(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/tool/cli.py": "import sys\n\nsys.exit(1)\n",
            "edgar_sec/pipelines/tool/operator.py": "import sys\n\nsys.exit(1)\n",
        },
    )
    assert clean_exit.scan_clean_exit() == []


def test_clean_exit_ignores_tests(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"tests/test_thing.py": "import sys\n\nsys.exit(1)\n"},
    )
    assert clean_exit.scan_clean_exit() == []


def test_environment_flags_direct_os_environ(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/thing.py": (
                "import os\n\n\ndef read() -> str:\n"
                "    return os.environ['SEC_USER_AGENT']\n"
            )
        },
    )
    assert environment.scan_environment_access()


def test_environment_allows_runtime_env_module(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/foundation/runtime/env.py": (
                "import os\n\n\ndef read() -> str:\n"
                "    return os.environ.get('X', '')\n"
            )
        },
    )
    assert environment.scan_environment_access() == []


def test_artifact_paths_flags_hardcoded_literal(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/pipelines/paths.py": 'ROOT = ".artifacts"\n'},
    )
    assert paths.scan_artifact_paths()


def test_artifact_paths_allows_path_resolver(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/foundation/runtime/paths.py": 'ROOT = ".artifacts"\n'},
    )
    assert paths.scan_artifact_paths() == []


def test_layers_flag_upward_import(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/domain/models.py": (
                "from edgar_sec.infra.storage.parquet import write_parquet_table\n"
            )
        },
    )
    assert layers.scan_layer_boundary()


def test_layers_flag_relative_upward_import(synthetic_repo: Path) -> None:
    """``..`` from a module directly inside ``foundation/`` resolves to
    ``edgar_sec.infra.storage`` — Layer 0 reaching Layer 2.
    """
    _build_repo(
        synthetic_repo,
        {"edgar_sec/foundation/checks.py": ("from ..infra.storage import duckdb\n")},
    )
    findings = layers.scan_layer_boundary()
    assert findings
    assert "infra" in findings[0].message


def test_layers_flag_relative_upward_import_from_nested_module(
    synthetic_repo: Path,
) -> None:
    """Depth matters: two dots from foundation/x/y.py is foundation, not root."""
    _build_repo(
        synthetic_repo,
        {"edgar_sec/foundation/x/y.py": ("from ..infra.storage import duckdb\n")},
    )
    # `..` from a subpackage names a nonexistent module, not an upward import, so it
    # must not be reported as a layer violation.
    assert layers.scan_layer_boundary() == []


def test_layers_flag_relative_sibling_layer_import(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/domain/a.py": ("from ..infra.broker import sec_broker\n")},
    )
    assert layers.scan_layer_boundary()


def test_layers_allow_downward_import(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/worker.py": (
                "from edgar_sec.engine.submissions.builder import normalize_submissions\n"
            )
        },
    )
    assert layers.scan_layer_boundary() == []


def test_secrets_flag_committed_api_key(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/pipelines/thing.py": ('API_KEY = "abcdef0123456789abcdef"\n')},
    )
    assert secrets_scanner.scan_secrets_leakage()


def test_secrets_flag_github_token(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/thing.py": (
                'TOKEN = "ghp_0123456789abcdefghijklmnopqrstuvwxyz"\n'
            )
        },
    )
    assert secrets_scanner.scan_secrets_leakage()


def test_secrets_ignore_short_and_dynamic_values(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/thing.py": (
                'SECRET = "short"\nAPI_KEY = get_env("SEC_API_KEY")\n'
            )
        },
    )
    assert secrets_scanner.scan_secrets_leakage() == []


def test_file_length_flags_long_module(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/pipelines/long_mod.py": "x = 1\n" * 801},
    )
    findings = length.scan_file_length()
    assert len(findings) == 1
    assert findings[0].path == "edgar_sec/pipelines/long_mod.py"
    assert findings[0].line == 801


def test_file_length_ignores_tests(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"tests/pipelines/test_long_mod.py": "x = 1\n" * 900},
    )
    assert length.scan_file_length() == []
