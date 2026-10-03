"""Immutable publication contract for target-plan bundles.

A published plan is a selectable work order. Each bundle is assembled in a
staging directory that is a *sibling* of its destination, so the final
``os.replace`` stays on one filesystem and is therefore atomic. A published
bundle is never partially visible.

Reuse policy: an exact rerun reuses the published bundle; an incomplete or
diverging directory is a conflict that must be removed deliberately rather than
being rewritten in place.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from edgar_sec.domain.filing_catalog.schemas import SCOPE_POLICY
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.duckdb import connect, sql_literal
from edgar_sec.pipelines.filing_catalog.paths import (
    LOCATOR_GROUPS_NAME,
    PLAN_FILE_NAME,
    PLAN_TARGETS_DIR_NAME,
    REQUIRED_PLAN_FILES,
    SEED_FILERS_NAME,
    SELECTION_REPORT_NAME,
    form_partition_name,
)

# Bump when the plan document or selection report changes shape. 1.1 added the
# pinned seed sidecar and the selection fingerprint, both of which a reused
# bundle must now carry, so bundles published under 1.0 are not reusable as 1.1.
# 1.2 adds the date selection to the deterministic plan document, and to the
# selection report along with the resolved era bands and the form-by-era
# allocation, so a reader no longer has to re-derive what a plan selected.
TARGET_PLAN_SCHEMA_VERSION = "1.2"


class PlanConflictError(RuntimeError):
    """A published plan directory exists but does not match the request."""


def plan_identity(payload: dict[str, Any]) -> str:
    """Derive a content-addressed plan id from the request that defines it.

    The same catalog and the same filters always yield the same id, so an exact
    rerun resolves to the same published bundle instead of forking a new one.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def plan_locator_keys(plan_dir: str | Path) -> list[str]:
    """Read a published plan's selected locator keys, in file order.

    The read runs on an in-memory DuckDB connection and writes nothing beside
    the plan, so an interrupted read cannot leave stray state inside an
    immutable published bundle.
    """
    root = Path(plan_dir).resolve()
    locator_path = root / LOCATOR_GROUPS_NAME
    if not locator_path.is_file():
        raise FileNotFoundError(f"plan locator groups not found: {locator_path}")
    with connect() as con:
        rows = con.execute(
            f"SELECT document_locator_key FROM read_parquet("
            f"{sql_literal(str(locator_path))}) ORDER BY document_locator_key"
        ).fetchall()
    return [str(row[0]) for row in rows]


def plan_fingerprint(plan_meta: dict[str, Any], locator_keys: list[str]) -> str:
    """Content digest of a plan's identity and its selected locators.

    Binds the fingerprint to the *selection*, not just the request, so two runs
    that requested the same thing but selected differently do not share one.

    The guarantee is deliberately narrow: this covers the work order -- the set
    of documents the plan says to fetch -- and not the bytes of every Parquet in
    the bundle. A digest over every file would make publication proportional to
    the size of the plan it is publishing.
    """
    return canonical_hash(
        {
            "plan_id": plan_meta.get("plan_id"),
            "catalog_id": plan_meta.get("catalog_id"),
            "scope": plan_meta.get("scope"),
            "locator_keys": sorted(locator_keys),
        }
    )[:32]


def plan_bundle_complete(plan_dir: Path, scope: str = "") -> bool:
    """Report whether a plan bundle holds every required published artifact.

    Completeness is checked by matching the on-disk partition set against the
    plan's own recorded ``counts`` rather than by asking whether any partition
    exists, so a legitimately empty plan (every filter excluded everything) is
    still reusable and a bundle that lost a shard is caught.

    A policy plan additionally owns the seed sidecar it was selected against, so
    a bundle missing it cannot reproduce its own selection and is not complete.
    """
    if not all((plan_dir / name).is_file() for name in REQUIRED_PLAN_FILES):
        return False
    if scope == SCOPE_POLICY and not (plan_dir / SEED_FILERS_NAME).is_file():
        return False
    targets_dir = plan_dir / PLAN_TARGETS_DIR_NAME
    if not targets_dir.is_dir():
        return False
    published = _load_plan_json(plan_dir)
    if published is None:
        return False
    counts = published.get("counts")
    if not isinstance(counts, dict):
        return False
    expected = {f"form={form_partition_name(form)}" for form in counts}
    present = {
        entry.name
        for entry in targets_dir.glob("form=*")
        if entry.is_dir() and (entry / "data.parquet").is_file()
    }
    return present == expected


def _load_plan_json(plan_dir: Path) -> dict[str, Any] | None:
    path = plan_dir / PLAN_FILE_NAME
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _verify_selection_fingerprint(plan_dir: Path, published: dict[str, Any]) -> None:
    """Refuse a bundle whose work order no longer matches its recorded selection.

    A plan is reused rather than rebuilt whenever the request is unchanged, so
    the published locator list is trusted on the strength of the fingerprint
    written with it. Without this check a bundle whose ``locator_groups.parquet``
    was edited or truncated still passes every structural test, and the next
    acquirer fetches a work order the plan never committed to.

    A bundle that records no fingerprint is refused rather than accepted: it was
    published under a contract that did not carry one, and silently recomputing
    it here would bless an unverifiable artifact.
    """
    recorded = str(published.get("plan_fingerprint") or "")
    if not recorded:
        raise PlanConflictError(
            f"plan bundle at {plan_dir} records no selection fingerprint; "
            "remove it and rerun to republish under the current plan contract"
        )
    actual = plan_fingerprint(published, plan_locator_keys(plan_dir))
    if actual != recorded:
        raise PlanConflictError(
            f"plan bundle at {plan_dir} no longer matches its selection fingerprint "
            f"(recorded {recorded}, found {actual}); remove it and republish"
        )


def reuse_existing_plan(
    final_dir: Path,
    plan_id: str,
    scope: str,
    *,
    expected_meta: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return a published bundle when it already satisfies the request.

    Returns ``None`` when nothing is published yet. Raises
    :class:`PlanConflictError` when a directory exists but is incomplete or
    describes a different request, because silently rewriting it would destroy
    an immutable published artifact.
    """
    if not final_dir.exists():
        return None

    published = _load_plan_json(final_dir)
    if published is None:
        raise PlanConflictError(f"plan bundle at {final_dir} has no readable plan.json")

    # Identity before completeness: a directory holding a different request is
    # a request conflict whether or not it is also incomplete, and reporting it
    # as merely incomplete would send an operator to rebuild a bundle that can
    # never satisfy this request.
    if published.get("plan_id") != plan_id or published.get("scope") != scope:
        raise PlanConflictError(
            f"plan bundle at {final_dir} describes a different request; remove "
            "it or publish under a different plan id"
        )

    if not plan_bundle_complete(final_dir, scope):
        raise PlanConflictError(
            f"incomplete plan bundle at {final_dir}; remove it and rerun to republish"
        )

    _verify_selection_fingerprint(final_dir, published)

    if expected_meta:
        mismatched = {
            key: (expected_meta[key], published.get(key))
            for key in expected_meta
            if published.get(key) != expected_meta[key]
        }
        if mismatched:
            raise PlanConflictError(
                f"plan bundle at {final_dir} diverges from the current request: "
                f"{sorted(mismatched)}"
            )

    return published


def publish_plan_bundle(staging_dir: Path, final_dir: Path) -> None:
    """Move a fully built staging bundle into its published location.

    ``os.replace`` is atomic only within a filesystem, which is why the staging
    directory is created as a sibling of ``final_dir``.
    """
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging_dir, final_dir)


@contextmanager
def staged_plan_bundle(final_dir: Path, plan_id: str) -> Iterator[Path]:
    """Yield a sibling staging directory and publish it atomically on success.

    On any failure the staging directory is removed, so a partial bundle is
    never left where a later run could mistake it for published state.
    """
    staging_dir = final_dir.parent / f".{final_dir.name}.staging.{plan_id}"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield staging_dir
    except BaseException:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    else:
        if final_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise PlanConflictError(
                f"plan bundle appeared at {final_dir} during publication"
            )
        publish_plan_bundle(staging_dir, final_dir)


def write_plan_documents(
    staging_dir: Path,
    plan_meta: dict[str, Any],
    selection_report: dict[str, Any],
) -> dict[str, Any]:
    """Write the two required JSON documents of a plan bundle.

    The selection fingerprint is stamped here, from the locator groups the
    bundle already holds, so it describes what was actually published rather
    than what the caller intended to publish. Stamping at one point also means
    no scope can forget it.

    Returns the stamped document, because a caller that later rewrites
    ``plan.json`` -- expansion does, to add lineage -- must carry the stamp with
    it or the bundle stops verifying.
    """
    stamped = dict(plan_meta)
    stamped["plan_fingerprint"] = plan_fingerprint(
        stamped, plan_locator_keys(staging_dir)
    )
    atomic_write_json(staging_dir / PLAN_FILE_NAME, stamped, indent=2)
    atomic_write_json(staging_dir / SELECTION_REPORT_NAME, selection_report, indent=2)
    return stamped


__all__ = [
    "TARGET_PLAN_SCHEMA_VERSION",
    "PlanConflictError",
    "plan_bundle_complete",
    "plan_fingerprint",
    "plan_identity",
    "plan_locator_keys",
    "publish_plan_bundle",
    "reuse_existing_plan",
    "staged_plan_bundle",
    "write_plan_documents",
]
