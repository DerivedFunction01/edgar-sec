"""Fixture lineage validation, as pure functions.

A fixture is a recorded set of raw payloads plus a manifest saying which plan
produced it. Replaying a plan against a fixture built from a *different* plan
silently produces a wrong answer, so the four identity axes below are checked
before any payload is read.

The checks are pure comparisons over two dicts, with no storage dependency and
no transaction, so they are directly testable.

The comparison is deliberately asymmetric: a manifest field is only checked when
*both* sides declare it. A fixture that records no lineage is legitimate input,
and refusing it would strand it, so a missing field means "unknown", not
"mismatched". What the validator does refuse is a declared mismatch.
"""

from __future__ import annotations

from typing import Any

#: Manifest field paired with the plan field it must agree with.
_LINEAGE_AXES: tuple[tuple[str, str, str], ...] = (
    ("catalog_id", "catalog_id", "catalog"),
    ("policy_corpus", "policy_corpus", "policy corpus"),
    ("seed_fingerprint", "seed_fingerprint", "seed CIK set"),
)


class FixtureLineageError(ValueError):
    """A fixture and a plan disagree on a recorded identity axis."""


def _normalized_forms(value: Any) -> set[str]:
    if not value:
        return set()
    if isinstance(value, str):
        return {value.strip().upper()}
    return {str(form).strip().upper() for form in value if str(form).strip()}


def check_fixture_lineage(manifest: dict[str, Any], plan: dict[str, Any]) -> None:
    """Raise :class:`FixtureLineageError` when a declared identity axis differs.

    Args:
        manifest: the fixture's recorded lineage.
        plan: the plan about to be replayed against the fixture.
    """
    for manifest_field, plan_field, label in _LINEAGE_AXES:
        recorded = manifest.get(manifest_field)
        requested = plan.get(plan_field)
        if recorded and requested and recorded != requested:
            raise FixtureLineageError(
                f"fixture and plan use different {label}s "
                f"({manifest_field}={recorded!r} != {plan_field}={requested!r})"
            )

    manifest_forms = _normalized_forms(manifest.get("forms"))
    plan_forms = _normalized_forms(plan.get("forms"))
    if manifest_forms and plan_forms and manifest_forms != plan_forms:
        raise FixtureLineageError(
            "fixture and plan use different form selections "
            f"({sorted(manifest_forms)} != {sorted(plan_forms)})"
        )


def is_fixture_compatible(manifest: dict[str, Any], plan: dict[str, Any]) -> bool:
    """Return whether a fixture and plan agree on every declared identity axis."""
    try:
        check_fixture_lineage(manifest, plan)
    except FixtureLineageError:
        return False
    return True


def fixture_lineage_status(manifest: dict[str, Any]) -> str:
    """Classify how much lineage a manifest actually records.

    ``unknown`` is the honest answer for a fixture captured before lineage was
    tracked; it is not a claim that the fixture is valid for any plan.
    """
    if not any(manifest.get(field) for field, _plan, _label in _LINEAGE_AXES):
        return "unknown"
    if not _normalized_forms(manifest.get("forms")):
        return "partial"
    return "recorded"


__all__ = [
    "FixtureLineageError",
    "check_fixture_lineage",
    "fixture_lineage_status",
    "is_fixture_compatible",
]
