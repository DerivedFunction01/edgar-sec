"""Pins for the dataset-path home (Wave 2B).
The resolver lives in ``engine.company_family.cohort``;
the cohort pipeline binds it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.engine.company_family.cohort import dataset_path
from edgar_sec.pipelines.cohort import operations


def test_binding_is_the_cohort_home() -> None:
    assert operations._dataset is dataset_path


def test_dataset_verdicts(tmp_path: Path) -> None:
    target = tmp_path / "cohort.parquet"
    target.write_bytes(b"x")
    assert dataset_path(target) == str(target.resolve())
    assert dataset_path(str(target)) == str(target.resolve())
    with pytest.raises(FileNotFoundError):
        dataset_path(tmp_path / "missing.parquet")
