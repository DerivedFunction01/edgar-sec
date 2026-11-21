"""Policies and catalog references a plan refuses."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.pipelines.filing_catalog.planning.policy import plan_policy
from tests.pipelines.filing_catalog.planning.policy_support import (
    _artifacts_root,
    _policy,
)


def test_policy_plan_rejects_a_policy_with_no_forms(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    policy = _policy()
    policy.forms = []
    with pytest.raises(ValueError, match="at least one form"):
        plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)


def test_plan_rejects_an_unsafe_catalog_reference(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    with pytest.raises(ValueError, match="invalid identifier"):
        plan_policy("../../etc", _policy(), artifacts_root)
