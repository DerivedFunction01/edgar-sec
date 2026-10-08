"""Tests for PlanEnvelope model and mapping protocol."""

from pathlib import Path
import pytest

from edgar_sec.domain.plan.envelope import PlanEnvelope


def test_plan_envelope_requires_non_empty_plan_id() -> None:
    """Empty or whitespace-only plan_id must raise ValueError."""
    path = Path("/tmp/dummy/plan.json")
    with pytest.raises(ValueError, match="non-empty plan_id"):
        PlanEnvelope(plan_id="", manifest_path=path, raw={})
    with pytest.raises(ValueError, match="non-empty plan_id"):
        PlanEnvelope(plan_id="   ", manifest_path=path, raw={})


def test_plan_envelope_mapping_access() -> None:
    """PlanEnvelope implements Mapping and exposes properties."""
    path = Path("/tmp/plans/p123/plan.json")
    raw = {"plan_id": "p123", "catalog_id": "cat-1", "count": 42}
    env = PlanEnvelope(plan_id="p123", manifest_path=path, raw=raw)

    assert env.plan_id == "p123"
    assert env.plan_dir == path.parent
    assert env["catalog_id"] == "cat-1"
    assert env.get("count") == 42
    assert env.get("missing", "default") == "default"
    assert len(env) == 3
    assert set(iter(env)) == {"plan_id", "catalog_id", "count"}
    assert env.describe() == "p123"
    assert env.unit_count is None
