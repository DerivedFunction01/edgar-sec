"""Store-state rows: bulk-archive reads and the cache lifecycle.

Dataset stores arrive by source id alone; no dataset-specific code lives
here. Destructive cache rows exist only behind the typed confirm.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from edgar_sec.apps.client.operator_tools import (
    absent_result,
    error_result,
    json_native,
    key_value_result,
)
from edgar_sec.foundation.runtime.render import KeyValueRow

__all__ = [
    "GATHERERS",
    "SPECS",
    "BulkArchiveMemberOptions",
    "BulkArchiveOptions",
    "CacheClearOptions",
    "CacheStateOptions",
    "CacheVacuumOptions",
    "build_specs",
    "register",
]


def _f(default: Any, help_text: str):
    return field(default=default, metadata={"help": help_text})


_SOURCE_HELP = "Bulk-archive source id (e.g. a dataset store's id, carried as data). Empty lists the sources the store offers; a stored source renders its manifest."
_CONFIRM_CLEAR = "Typed confirm: must equal the operation id cache_clear exactly; any other value refuses and nothing is cleared."
_CONFIRM_VACUUM = "Typed confirm: must equal the operation id cache_vacuum exactly; any other value refuses and nothing is vacuumed."


@dataclass(frozen=True, slots=True)
class BulkArchiveOptions:
    """Options for listing bulk-archive sources or reading one manifest."""

    source_id: str = _f("", _SOURCE_HELP)
    sha256: str | None = _f(None, "Pins one stored archive digest; empty is newest.")
    limit: int = _f(50, "Maximum sources listed. Refused below 1.")


@dataclass(frozen=True, slots=True)
class BulkArchiveMemberOptions:
    """Options for reading one member of a stored bulk archive."""

    source_id: str = _f("", "Bulk-archive source id; required, carried as data.")
    member: str = _f("", "Member name inside the archive; required.")
    save_path: Path = _f(
        Path(""),
        "When set, the member's bytes are also written to this path and "
        "the result reports the path and size; empty reads without saving.",
    )


@dataclass(frozen=True, slots=True)
class CacheStateOptions:
    """Options for rendering cache statistics."""


@dataclass(frozen=True, slots=True)
class CacheClearOptions:
    """Options for clearing the caches, behind the typed confirm."""

    confirm: str = _f("", _CONFIRM_CLEAR)


@dataclass(frozen=True, slots=True)
class CacheVacuumOptions:
    """Options for vacuuming the response cache, behind the typed confirm."""

    confirm: str = _f("", _CONFIRM_VACUUM)


def _bulk_root(session: Any) -> Path | None:
    artifacts = getattr(session.facade, "artifacts_root", None)
    if not artifacts:
        try:
            from edgar_sec.foundation.runtime.paths import resolve_paths

            artifacts = resolve_paths().artifacts_root
        except Exception:  # noqa: BLE001 - no readable root reads as no store
            return None
    from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths

    return resolve_metadata_paths(artifacts).bulk_archives_root


def _bulk_sources(session: Any) -> list[str]:
    facade = session.facade
    for attribute in ("bulk_archive_sources", "bulk_sources", "archive_sources"):
        provider = getattr(facade, attribute, None)
        if callable(provider):
            return sorted(str(source) for source in provider())
    root = _bulk_root(session)
    if root is None or not root.is_dir():
        return []
    return sorted(
        child.name
        for child in root.iterdir()
        if child.is_dir() and child.name[:1] != "."
    )


def _manifest_dict(reference: Any) -> dict[str, Any]:
    manifest = getattr(reference, "manifest", None)
    if isinstance(manifest, dict):
        return json_native(manifest)
    fields = (
        "source_id",
        "source_url",
        "sha256",
        "byte_size",
        "member_count",
        "fetched_at",
        "sec_last_modified",
    )
    return {name: getattr(manifest, name, None) for name in fields}


def _execute_bulk_archive(options: BulkArchiveOptions, session: Any):
    from edgar_sec.apps.client.operator import OpResult

    title = "Bulk archive"
    if options.limit < 1:
        return error_result("key_value", "invalid_options", title, "limit below 1")
    if not options.source_id:
        sources = _bulk_sources(session)
        if not sources:
            return absent_result(
                "key_value",
                title,
                "no bulk-archive sources are stored",
                {"sources": []},
            )
        shown = sources[: options.limit]
        entries: list[dict[str, Any]] = []
        rows: list[KeyValueRow] = []
        for source_id in shown:
            entry: dict[str, Any] = {"source_id": source_id}
            reference = session.facade.bulk_archive(source_id)
            detail = "stored"
            if reference is not None:
                manifest = _manifest_dict(reference)
                entry["manifest"] = manifest
                detail = f"{manifest.get('member_count')} members"
            entries.append(entry)
            rows.append(KeyValueRow(source_id, detail))
        data = {"sources": entries, "present": True}
        return OpResult(
            kind="key_value",
            title=title,
            components=tuple(rows),
            data=data,
            total=len(sources),
            shown=len(shown),
            hints=("bulk_archive_member",),
        )
    reference = session.facade.bulk_archive(options.source_id, options.sha256)
    if reference is None:
        return absent_result(
            "key_value",
            title,
            f"no stored archive for source: {options.source_id}",
            {"source_id": options.source_id},
        )
    manifest = _manifest_dict(reference)
    data = {
        "source_id": options.source_id,
        "manifest": manifest,
        "path": str(getattr(reference, "path", "")),
        "present": True,
    }
    rows = (
        ("source", str(manifest.get("source_id") or options.source_id)),
        ("url", str(manifest.get("source_url") or "")),
        ("sha256", str(manifest.get("sha256") or "")),
        ("bytes", str(manifest.get("byte_size") or "")),
        ("members", str(manifest.get("member_count") or "")),
        ("fetched", str(manifest.get("fetched_at") or "")),
        ("sec modified", str(manifest.get("sec_last_modified") or "none")),
        ("path", data["path"]),
    )
    return key_value_result(title, data, rows, hints=("bulk_archive_member",))


def _execute_bulk_archive_member(options: BulkArchiveMemberOptions, session: Any):
    title = "Bulk archive member"
    if not options.source_id or not options.member:
        return error_result(
            "key_value",
            "invalid_options",
            title,
            "a source id and a member name are required",
        )
    try:
        payload = session.facade.bulk_archive_member(options.source_id, options.member)
    except ValueError as exc:
        return error_result("key_value", "not_found", title, str(exc))
    if payload is None:
        return absent_result(
            "key_value",
            title,
            f"no stored archive for source: {options.source_id}",
            {"source_id": options.source_id, "member": options.member},
        )
    data: dict[str, Any] = {
        "source_id": options.source_id,
        "member": options.member,
        "bytes": len(payload),
        "saved": False,
        "present": True,
    }
    rows = [
        ("source", options.source_id),
        ("member", options.member),
        ("bytes", str(len(payload))),
    ]
    if str(options.save_path) not in ("", "."):
        target = options.save_path
        if target.parent and str(target.parent) not in ("", "."):
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        data["saved"] = True
        data["save_path"] = str(target)
        data["size"] = len(payload)
        rows.append(("saved to", str(target)))
    return key_value_result(title, data, tuple(rows), hints=("bulk_archive",))


def _flatten_stats(stats: Any, prefix: str = "") -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if isinstance(stats, dict):
        for key in sorted(stats):
            rows.extend(_flatten_stats(stats[key], f"{prefix}{key}."))
    else:
        rows.append((prefix.rstrip("."), str(stats)))
    return rows


def _execute_cache_state(options: CacheStateOptions, session: Any):
    title = "Cache state"
    try:
        stats = session.facade.cache_stats()
    except Exception:  # noqa: BLE001 - a stats failure reads as honest absence
        stats = None
    if not isinstance(stats, dict):
        return absent_result(
            "key_value",
            title,
            "cache statistics are unavailable",
            {"stats": None},
        )
    rows = _flatten_stats(stats)
    data = {"stats": json_native(stats), "present": True}
    return key_value_result(title, data, rows, hints=("cache_clear", "cache_vacuum"))


def _execute_cache_clear(options: CacheClearOptions, session: Any):
    title = "Clear cache"
    if options.confirm != "cache_clear":
        return error_result(
            "key_value",
            "refused",
            title,
            "clear refused: confirm must equal cache_clear exactly",
            {"confirmed": False},
        )
    cleared = session.facade.clear_cache()
    data = {"cleared": json_native(dict(cleared)), "confirmed": True}
    rows = tuple((str(k), str(v)) for k, v in dict(cleared).items())
    return key_value_result(title, data, rows, hints=("cache_state",))


def _execute_cache_vacuum(options: CacheVacuumOptions, session: Any):
    title = "Vacuum cache"
    if options.confirm != "cache_vacuum":
        return error_result(
            "key_value",
            "refused",
            title,
            "vacuum refused: confirm must equal cache_vacuum exactly",
            {"confirmed": False},
        )
    session.facade.vacuum_cache()
    data = {"vacuumed": True, "confirmed": True}
    return key_value_result(title, data, (("vacuum", "done"),), hints=("cache_state",))


_SPEC_ROWS = (
    (
        "bulk_archive",
        "Bulk archive",
        BulkArchiveOptions,
        _execute_bulk_archive,
        "reads_state",
    ),
    (
        "bulk_archive_member",
        "Read a bulk-archive member",
        BulkArchiveMemberOptions,
        _execute_bulk_archive_member,
        "reads_state",
    ),
    (
        "cache_state",
        "Cache state",
        CacheStateOptions,
        _execute_cache_state,
        "reads_state",
    ),
    (
        "cache_clear",
        "Clear cache (typed confirm)",
        CacheClearOptions,
        _execute_cache_clear,
        "destructive",
    ),
    (
        "cache_vacuum",
        "Vacuum cache (typed confirm)",
        CacheVacuumOptions,
        _execute_cache_vacuum,
        "destructive",
    ),
)


def build_specs() -> tuple:
    """Build this module's registry rows; operator imports resolve at call time."""
    from edgar_sec.apps.client.operator import OperationSpec

    return tuple(
        OperationSpec(
            id=op_id,
            label=label,
            options_type=options_type,
            effect=effect,
            requires="none",
            result_kind="key_value",
            hints=("session_summary",),
            executor=executor,
        )
        for op_id, label, options_type, executor, effect in _SPEC_ROWS
    )


def register(registry: dict) -> dict:
    """Add this module's rows to ``registry``, refusing duplicate ids."""
    from edgar_sec.apps.client.operator import assemble_registry

    specs = build_specs()
    assemble_registry(registry.values(), specs)
    for spec in specs:
        registry[spec.id] = spec
    return registry


def __getattr__(name: str):
    if name == "SPECS":
        return build_specs()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _generic(session: Any, options_type: type):
    from edgar_sec.apps.client.operator_selection import _gather_options

    return _gather_options(session, options_type)


GATHERERS: dict[str, Callable[[Any], Any]] = {
    "bulk_archive": lambda session: _generic(session, BulkArchiveOptions),
    "bulk_archive_member": lambda session: _generic(session, BulkArchiveMemberOptions),
    "cache_state": lambda session: _generic(session, CacheStateOptions),
    "cache_clear": lambda session: _generic(session, CacheClearOptions),
    "cache_vacuum": lambda session: _generic(session, CacheVacuumOptions),
}
