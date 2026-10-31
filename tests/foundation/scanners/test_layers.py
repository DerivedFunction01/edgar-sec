from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.scanners import layers


def _build_repo(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@pytest.fixture()
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


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
    _build_repo(
        synthetic_repo,
        {"edgar_sec/foundation/checks.py": "from ..infra.storage import duckdb\n"},
    )
    findings = layers.scan_layer_boundary()
    assert findings
    assert "infra" in findings[0].message


def test_layers_ignore_relative_import_that_resolves_within_layer(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/foundation/x/y.py": "from ..infra.storage import duckdb\n"},
    )
    assert layers.scan_layer_boundary() == []


def test_layers_flag_relative_sibling_layer_import(synthetic_repo: Path) -> None:
    _build_repo(
        synthetic_repo,
        {"edgar_sec/domain/a.py": "from ..infra.broker import sec_broker\n"},
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


def test_layers_allow_matching_cross_pipeline_paths_imports(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/alpha/paths.py": (
                "from edgar_sec.pipelines.beta.paths import SHARED_NAME\n"
            ),
            "edgar_sec/pipelines/beta/paths.py": "SHARED_NAME = 'shared'\n",
        },
    )
    assert layers.scan_layer_boundary() == []


def test_layers_allow_matching_cross_pipeline_schemas_imports(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/alpha/schemas.py": (
                "from edgar_sec.pipelines.beta.schemas import SharedSchema\n"
            ),
            "edgar_sec/pipelines/beta/schemas.py": "SharedSchema = object\n",
        },
    )
    assert layers.scan_layer_boundary() == []


@pytest.mark.parametrize(
    "caller,target,statement",
    [
        ("operator.py", "paths.py", "from edgar_sec.pipelines.beta.paths import X\n"),
        ("paths.py", "schemas.py", "from edgar_sec.pipelines.beta.schemas import X\n"),
        (
            "schemas.py",
            "schemas.py",
            "from edgar_sec.pipelines.beta.schemas import X as Y\n",
        ),
        (
            "schemas.py",
            "schemas.py",
            "from edgar_sec.pipelines.beta.schemas import *\n",
        ),
        ("worker.py", "worker.py", "from edgar_sec.pipelines.beta.worker import run\n"),
    ],
)
def test_layers_reject_forbidden_cross_pipeline_imports(
    synthetic_repo: Path, caller: str, target: str, statement: str
) -> None:
    _build_repo(
        synthetic_repo,
        {
            f"edgar_sec/pipelines/alpha/{caller}": statement,
            f"edgar_sec/pipelines/beta/{target}": "X = object\n",
        },
    )
    findings = layers.scan_layer_boundary()
    assert len(findings) == 1
    assert "cross-pipeline" in findings[0].message


def test_layers_reject_cross_pipeline_path_import_cycles(
    synthetic_repo: Path,
) -> None:
    _build_repo(
        synthetic_repo,
        {
            "edgar_sec/pipelines/alpha/paths.py": (
                "from edgar_sec.pipelines.beta.paths import B_NAME\n"
            ),
            "edgar_sec/pipelines/beta/paths.py": (
                "from edgar_sec.pipelines.alpha.paths import A_NAME\n"
            ),
        },
    )
    findings = layers.scan_layer_boundary()
    assert len(findings) == 1
    assert "import cycle" in findings[0].message
