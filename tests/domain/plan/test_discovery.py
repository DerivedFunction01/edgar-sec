"""Tests for read_plan_envelope and discover_plans."""

import json
from pathlib import Path

from edgar_sec.domain.plan.discovery import discover_plans, read_plan_envelope
from edgar_sec.domain.plan.envelope import PlanEnvelope


def test_read_plan_envelope_invalid(tmp_path: Path) -> None:
    """Missing, corrupt, or plan_id-lacking manifests return None."""
    assert read_plan_envelope(tmp_path / "nonexistent") is None

    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()
    assert read_plan_envelope(empty_dir) is None

    corrupt = tmp_path / "corrupt"
    corrupt.mkdir()
    (corrupt / "plan.json").write_text("{bad json", encoding="utf-8")
    assert read_plan_envelope(corrupt) is None

    no_id = tmp_path / "no_id"
    no_id.mkdir()
    (no_id / "plan.json").write_text('{"other": 1}', encoding="utf-8")
    assert read_plan_envelope(no_id) is None


def test_discover_plans_sorting_and_filtering(tmp_path: Path) -> None:
    """Discovers plans, sorts by mtime descending, and applies filter."""
    plans_root = tmp_path / "plans"
    plans_root.mkdir()

    for idx, name in enumerate(("plan_a", "plan_b", "plan_c"), start=1):
        p_dir = plans_root / name
        p_dir.mkdir()
        (p_dir / "plan.json").write_text(
            json.dumps({"plan_id": name, "seq": idx}), encoding="utf-8"
        )

    # Empty / non-plan sibling
    (plans_root / "not_a_plan").mkdir()

    plans = discover_plans(plans_root)
    assert len(plans) == 3
    assert {p.plan_id for p in plans} == {"plan_a", "plan_b", "plan_c"}

    filtered = discover_plans(plans_root, filter_fn=lambda p: int(p.get("seq", 0)) > 1)
    assert len(filtered) == 2
    assert {p.plan_id for p in filtered} == {"plan_b", "plan_c"}


def test_discover_plans_custom_class(tmp_path: Path) -> None:
    """Custom PlanEnvelope subclass can be passed via envelope_cls."""

    class CustomEnvelope(PlanEnvelope):
        @property
        def unit_count(self) -> int | None:
            return int(self.raw.get("units", 0))

    p_dir = tmp_path / "plans" / "custom"
    p_dir.mkdir(parents=True)
    (p_dir / "plan.json").write_text(
        json.dumps({"plan_id": "custom", "units": 100}), encoding="utf-8"
    )

    plans = discover_plans(tmp_path / "plans", envelope_cls=CustomEnvelope)
    assert len(plans) == 1
    assert isinstance(plans[0], CustomEnvelope)
    assert plans[0].unit_count == 100
