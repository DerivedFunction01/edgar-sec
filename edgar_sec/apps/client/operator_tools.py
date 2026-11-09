"""Read/tool rows over state: feed events, EFTS, and local text search.

Rows contribute through ``register(registry)`` and ``GATHERERS``; operator
imports stay inside functions so this module loads standalone.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from edgar_sec.foundation.runtime.render import Grid, KeyValueRow, ProseRow

__all__ = [
    "GATHERERS",
    "SPECS",
    "EftsCaptureOptions",
    "EftsSearchOptions",
    "FeedEventsOptions",
    "FeedSeedOptions",
    "LocalSearchOptions",
    "LocalSearchSeedOptions",
    "absent_result",
    "build_specs",
    "coverage_dict",
    "empty_accounting",
    "error_result",
    "json_native",
    "key_value_result",
    "record_external_run",
    "register",
]


def _f(default: Any, help_text: str):
    return field(default=default, metadata={"help": help_text})


_FEED_HELP = "Filter for the feed-events read; an unstored ledger renders as honest absence, never an empty grid."
_LIMIT_HELP = "Maximum rows shown; total versus shown is declared. Refused below 1."
_INTO_HELP = "Names the target set; the seed makes it the current set."
_EFTS_HELP = "EFTS query field, read exactly as the endpoint reads it; a query needs text, forms, or ciks, and dates are a pair or neither."


@dataclass(frozen=True, slots=True)
class FeedEventsOptions:
    """Options for reading feed-ledger events."""

    forms: tuple[str, ...] = _f((), _FEED_HELP)
    sources: tuple[str, ...] = _f((), "Ledger sources to filter by; see forms.")
    filed_from: str | None = _f(None, "Earliest filing date (ISO); empty is open.")
    filed_to: str | None = _f(None, "Latest filing date (ISO); empty is open.")
    limit: int | None = _f(
        None, "Caps events at the ledger query; empty uses the facade default."
    )


@dataclass(frozen=True, slots=True)
class FeedSeedOptions(FeedEventsOptions):
    """Options for seeding a set from feed-ledger events."""

    into: str = _f("main", _INTO_HELP)


@dataclass(frozen=True, slots=True)
class EftsSearchOptions:
    """Options for a live EFTS search; nothing is persisted."""

    text: str = _f("", _EFTS_HELP)
    forms: tuple[str, ...] = _f((), "Forms filter; see text for the query rules.")
    ciks: tuple[str, ...] = _f((), "CIK filter; see text for the query rules.")
    tickers: tuple[str, ...] = _f((), "Tickers, resolved to CIKs by the facade.")
    items: tuple[str, ...] = _f((), "Form item filter (e.g. 2.02).")
    startdt: str | None = _f(None, "Start date; must pair with enddt.")
    enddt: str | None = _f(None, "End date; must pair with startdt.")
    max_hits: int | None = _f(None, "Retrieval cap; empty is one page.")
    exhaustive: bool = _f(False, "Date-sliced retrieval past the ceiling.")
    limit: int = _f(20, _LIMIT_HELP)


@dataclass(frozen=True, slots=True)
class EftsCaptureOptions:
    """Options for an EFTS capture: an EftsQuery shape plus a confirm flag."""

    text: str = _f("", _EFTS_HELP)
    forms: tuple[str, ...] = _f((), "Forms filter; see text for the query rules.")
    ciks: tuple[str, ...] = _f((), "CIK filter; see text for the query rules.")
    items: tuple[str, ...] = _f((), "Form item filter (e.g. 2.02).")
    startdt: str | None = _f(None, "Start date; must pair with enddt.")
    enddt: str | None = _f(None, "End date; must pair with startdt.")
    sec_syntax: str | None = _f(None, "Labelled SEC syntax; not with text.")
    exhaustive: bool = _f(False, "Date-sliced capture past the ceiling.")
    confirm: bool = _f(
        False,
        "The confirmed act: capture writes the facade's only persistence "
        "artefact for a search. Refusal: without confirm set, the row refuses "
        "and writes nothing.",
    )


@dataclass(frozen=True, slots=True)
class LocalSearchOptions:
    """Options for searching acquired holdings through the local index."""

    query: str = _f("", "Search text; an empty query is refused.")
    mode: str = _f("bm25", "Engine mode the index serves (bm25 by default).")
    accessions: tuple[str, ...] = _f((), "Scope to these accessions.")
    ciks: tuple[int, ...] = _f((), "Scope to these CIKs.")
    forms: tuple[str, ...] = _f((), "Scope to these forms.")
    date_from: str | None = _f(None, "Earliest filing date; empty is open.")
    date_to: str | None = _f(None, "Latest filing date; empty is open.")
    attachment_scope: str = _f("all_documents", "Attachment scope the index searches.")
    limit: int = _f(50, "Maximum hits the index returns. Refused below 1.")


@dataclass(frozen=True, slots=True)
class LocalSearchSeedOptions(LocalSearchOptions):
    """Options for seeding or intersecting a set from local-search hits."""

    into: str = _f("main", _INTO_HELP)
    action: str = _f(
        "seed",
        "Either seed (the hits become the named set) or intersect (the "
        "named/current set is narrowed to the hits). Any other value refuses.",
    )


def json_native(value: Any) -> Any:
    """Recursively convert a value to JSON-native shapes."""
    if isinstance(value, dict):
        return {str(k): json_native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_native(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


def error_result(kind: str, code: str, title: str, message: str, data=None):
    """A coded result with the message as its sole prose component."""
    from edgar_sec.apps.client.operator import OpResult

    return OpResult(
        kind=kind,
        title=title,
        components=(ProseRow(message),),
        data={**(data or {}), "message": message},
        error_code=code,
    )


def absent_result(kind: str, title: str, message: str, data=None):
    """An honest-absence result: prose line plus ``present`` false."""
    return error_result(
        kind, "absent", title, message, {**(data or {}), "present": False}
    )


def key_value_result(title: str, data: dict, rows: Iterable[tuple[str, str]], **extra):
    """A key-value result whose total is its row count."""
    from edgar_sec.apps.client.operator import OpResult

    components = tuple(KeyValueRow(k, v) for k, v in rows)
    return OpResult(
        kind="key_value",
        title=title,
        components=components,
        data=data,
        total=len(components),
        shown=len(components),
        **extra,
    )


def record_external_run(
    session: Any,
    *,
    operation: str,
    options_data: dict,
    selection: dict,
    started: datetime,
    cache_before: Any,
    engine: str,
    result_info: dict,
    accounting: dict,
    error_code: str | None = None,
    error: str | None = None,
) -> tuple[str, Path]:
    """Write one run record for an external row through the shared machinery."""
    from edgar_sec.apps.client import operator_run_records as records

    record_id = f"op-{started.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    base = {
        "record_id": record_id,
        "operation": operation,
        "started_at": started.isoformat(),
        "options": json_native(options_data),
        "selection": json_native(selection),
        "mode": session.read_context.mode,
        "snapshot": session.read_context.snapshot,
    }
    path = records.finish_record(
        session,
        base,
        engine=engine,
        cache=records.cache_line(cache_before, records.cache_stats(session)),
        table_counts={},
        member_accounting=accounting,
        result=json_native(result_info),
        error_code=error_code,
        error=error,
    )
    return record_id, path


def empty_accounting(source: str) -> dict:
    """A member accounting with no successes, for a facade call that raised."""
    return {
        "source": source,
        "success_count": 0,
        "successes": [],
        "error_count": 0,
        "errors": [],
        "other_count": 0,
    }


def _feed_events(session: Any, options: FeedEventsOptions):
    return session.facade.feed_events(
        forms=tuple(options.forms),
        sources=tuple(options.sources),
        filed_from=options.filed_from,
        filed_to=options.filed_to,
        limit=options.limit,
    )


def _event_rows(result: Any) -> list[dict[str, Any]]:
    return [
        {
            "accession": str(event.accession),
            "cik": str(event.cik),
            "form": str(event.form),
            "company": str(event.company_name),
            "filing_date": str(event.filing_date),
            "sources": [str(s) for s in event.sources],
            "link": str(event.link),
        }
        for event in result.events
    ]


def _execute_feed_events(options: FeedEventsOptions, session: Any):
    from edgar_sec.apps.client.operator import OpResult

    title = "Feed events"
    if options.limit is not None and options.limit < 1:
        return error_result("grid", "invalid_options", title, "limit below 1")
    result = _feed_events(session, options)
    if not result.ledger_present:
        return absent_result(
            "grid",
            title,
            "no feed ledger is stored; feed events are absent",
            {"ledger_present": False, "snapshot_id": None, "events": []},
        )
    rows = _event_rows(result)
    grid = Grid(
        headers=("accession", "cik", "form", "company", "filed", "sources"),
        rows=tuple(
            (
                r["accession"],
                r["cik"],
                r["form"],
                r["company"],
                r["filing_date"],
                ", ".join(r["sources"]),
            )
            for r in rows
        ),
    )
    data = {
        "present": True,
        "ledger_present": True,
        "snapshot_id": result.snapshot_id,
        "events": rows,
        "limit": options.limit,
    }
    return OpResult(
        kind="grid",
        title=title,
        components=(grid,),
        data=data,
        total=len(rows),
        shown=len(rows),
        hints=("feed_seed",),
    )


def _execute_feed_seed(options: FeedSeedOptions, session: Any):
    from edgar_sec.apps.client.operator_selection import store_working_set

    title = "Seed set from feed events"
    if options.limit is not None and options.limit < 1:
        return error_result("key_value", "invalid_options", title, "limit below 1")
    result = _feed_events(session, options)
    if not result.ledger_present:
        return absent_result(
            "key_value",
            title,
            "no feed ledger is stored; nothing was seeded",
            {"ledger_present": False, "set": options.into, "count": 0},
        )
    accessions = list(dict.fromkeys(str(e.accession) for e in result.events))
    working = store_working_set(session, options.into, accessions)
    data = {
        "set": options.into,
        "count": len(working),
        "source": "feed_events",
        "snapshot_id": result.snapshot_id,
    }
    rows = (
        ("set", options.into),
        ("count", str(len(working))),
        ("source", "feed_events"),
    )
    return key_value_result(
        f"Seeded set {options.into}", data, rows, hints=("vars", "peek")
    )


def coverage_dict(coverage: Any) -> dict[str, Any]:
    """A coverage block as a JSON-native dict, fields exactly as carried."""
    if coverage is None:
        return {}
    if isinstance(coverage, dict):
        return json_native(coverage)
    if is_dataclass(coverage):
        return json_native(asdict(coverage))
    fields = (
        "total_value",
        "total_relation",
        "hits_returned",
        "truncated",
        "ceiling_reached",
        "items_cache_hazard",
    )
    return {name: getattr(coverage, name, None) for name in fields}


def _execute_efts_search(options: EftsSearchOptions, session: Any):
    from edgar_sec.apps.client.operator import OpResult

    title = "EFTS search"
    if options.limit < 1:
        return error_result("grid", "invalid_options", title, "limit below 1")
    if options.max_hits is not None and options.max_hits < 1:
        return error_result("grid", "invalid_options", title, "max_hits below 1")
    try:
        result = session.facade.full_text_search(
            text=options.text,
            forms=tuple(options.forms),
            ciks=tuple(options.ciks),
            tickers=tuple(options.tickers),
            items=tuple(options.items),
            startdt=options.startdt,
            enddt=options.enddt,
            max_hits=options.max_hits,
            exhaustive=options.exhaustive,
        )
    except ValueError as exc:
        return error_result("grid", "invalid_options", title, str(exc))
    coverage = coverage_dict(result.coverage)
    total = int(coverage.get("total_value") or 0)
    shown_hits = list(result.hits)[: options.limit]
    rows = [
        {
            "accession": str(hit.accession),
            "filename": str(hit.filename),
            "form": str(hit.form),
            "file_date": str(hit.file_date),
            "company": str(hit.display_names[0]) if hit.display_names else "",
            "score": hit.score,
        }
        for hit in shown_hits
    ]
    grid = Grid(
        headers=("accession", "file", "form", "filed", "company", "score"),
        rows=tuple(
            (
                r["accession"],
                r["filename"],
                r["form"],
                r["file_date"],
                r["company"],
                "" if r["score"] is None else str(r["score"]),
            )
            for r in rows
        ),
    )
    data = {"coverage": coverage, "hits": rows, "total_value": total}
    data["total_relation"] = coverage.get("total_relation")
    return OpResult(
        kind="grid",
        title=title,
        components=(grid,),
        data=data,
        total=total,
        shown=len(rows),
        hints=("efts_capture",),
    )


def _execute_efts_capture(options: EftsCaptureOptions, session: Any):
    from edgar_sec.apps.client import operator_run_records as records
    from edgar_sec.apps.client.efts import EftsQuery

    title = "Capture EFTS search"
    if not options.confirm:
        return error_result(
            "key_value",
            "refused",
            title,
            "capture refused: confirm is not set; nothing was written",
            {"confirmed": False},
        )
    try:
        query = EftsQuery(
            text=options.text,
            forms=tuple(options.forms),
            ciks=tuple(options.ciks),
            items=tuple(options.items),
            startdt=options.startdt,
            enddt=options.enddt,
            sec_syntax=options.sec_syntax,
        )
    except ValueError as exc:
        return error_result("key_value", "invalid_options", title, str(exc))
    started = datetime.now(UTC)
    cache_before = records.cache_stats(session)
    selection = {"kind": "efts_query", "query": asdict(query)}
    try:
        capture = session.facade.capture_full_text_search(
            query, exhaustive=options.exhaustive
        )
    except Exception as exc:  # noqa: BLE001 - a facade failure is a coded result
        record_id, _ = record_external_run(
            session,
            operation="efts_capture",
            options_data=asdict(options),
            selection=selection,
            started=started,
            cache_before=cache_before,
            engine="efts",
            result_info={"directory": "", "query_hash": "", "hits_returned": 0},
            accounting=empty_accounting("facade call raised before any result"),
            error_code="external_failure",
            error=str(exc),
        )
        return error_result(
            "key_value",
            "external_failure",
            title,
            str(exc),
            {"record_id": record_id, "confirmed": True},
        )
    coverage = coverage_dict(capture.coverage)
    accessions = [str(i.accession) for i in capture.identities]
    accounting = records.member_accounting(accessions, None)
    info = {
        "directory": str(capture.directory),
        "query_hash": str(capture.query_hash),
        "hits_returned": int(coverage.get("hits_returned") or 0),
    }
    record_id, path = record_external_run(
        session,
        operation="efts_capture",
        options_data=asdict(options),
        selection=selection,
        started=started,
        cache_before=cache_before,
        engine="efts",
        result_info=info,
        accounting=accounting,
    )
    data = {
        "capture": {
            "directory": info["directory"],
            "query_hash": info["query_hash"],
            "executed_at": str(capture.executed_at),
            "coverage": coverage,
        },
        "record_id": record_id,
        "record_path": str(path),
        "confirmed": True,
    }
    rows = (
        ("directory", info["directory"]),
        ("query hash", info["query_hash"]),
        ("hits", str(info["hits_returned"])),
        ("record", record_id),
    )
    return key_value_result(title, data, rows, hints=("inspect_past_run",))


def _search(session: Any, options: LocalSearchOptions):
    return session.facade.search_documents(
        options.query,
        mode=options.mode,
        accessions=tuple(options.accessions),
        ciks=tuple(options.ciks),
        forms=tuple(options.forms),
        date_from=options.date_from,
        date_to=options.date_to,
        attachment_scope=options.attachment_scope,
        limit=options.limit,
    )


def _hit_rows(result: Any) -> list[dict[str, Any]]:
    return [
        {
            "accession": str(hit.accession),
            "filename": str(hit.filename),
            "section": hit.section_name,
            "score": hit.score,
            "excerpt": str(hit.excerpt),
        }
        for hit in result.hits
    ]


def _execute_local_search(options: LocalSearchOptions, session: Any):
    from edgar_sec.apps.client.operator import OpResult

    title = "Local text search"
    if not options.query.strip():
        return error_result("grid", "invalid_options", title, "a query is required")
    if options.limit < 1:
        return error_result("grid", "invalid_options", title, "limit below 1")
    result = _search(session, options)
    coverage = coverage_dict(result.coverage)
    rows = _hit_rows(result)
    not_in_corpus = [str(t) for t in result.not_in_corpus]
    components: list[Any] = [
        ProseRow(f"{key}: {value}") for key, value in coverage.items()
    ]
    if rows:
        components.append(
            Grid(
                headers=("accession", "file", "section", "score"),
                rows=tuple(
                    (
                        r["accession"],
                        r["filename"],
                        str(r["section"] or ""),
                        "" if r["score"] is None else str(r["score"]),
                    )
                    for r in rows
                ),
            )
        )
    data = {
        "query": options.query,
        "mode": options.mode,
        "coverage": coverage,
        "not_in_corpus": not_in_corpus,
        "no_match": not rows and not not_in_corpus,
        "hits": rows,
    }
    return OpResult(
        kind="grid",
        title=title,
        components=tuple(components),
        data=data,
        total=len(rows),
        shown=len(rows),
        hints=("local_search_seed",),
    )


def _execute_local_search_seed(options: LocalSearchSeedOptions, session: Any):
    from edgar_sec.apps.client.operator_selection import (
        filter_result_to_accessions,
        store_working_set,
    )

    title = "Seed set from local search"
    if not options.query.strip():
        return error_result(
            "key_value", "invalid_options", title, "a query is required"
        )
    if options.limit < 1:
        return error_result("key_value", "invalid_options", title, "limit below 1")
    if options.action not in ("seed", "intersect"):
        return error_result(
            "key_value",
            "invalid_options",
            title,
            f"unknown action: {options.action}",
        )
    result = _search(session, options)
    hits = list(dict.fromkeys(str(h.accession) for h in result.hits))
    if options.action == "seed":
        working = store_working_set(session, options.into, hits)
        data = {"set": options.into, "count": len(working), "action": "seed"}
        data["source"] = "local_search"
        data["not_in_corpus"] = [str(t) for t in result.not_in_corpus]
        rows = (
            ("set", options.into),
            ("count", str(len(working))),
            ("action", "seed"),
        )
        return key_value_result(title, data, rows, hints=("vars", "peek"))
    base_name = options.into or session.current_set_name
    base = session.sets.get(base_name) if base_name else None
    if base is None:
        return error_result(
            "key_value",
            "not_found",
            title,
            f"set not found: {base_name or '(none)'}",
        )
    survivors = frozenset(base.accessions & frozenset(hits))
    retained = None
    if base.result is not None:
        retained = filter_result_to_accessions(base.result, survivors)
    working = store_working_set(session, base_name, survivors, result=retained)
    data = {"set": base_name, "count": len(working), "action": "intersect"}
    data["source"] = "local_search"
    data["base_count"] = len(base)
    rows = (("set", base_name), ("count", str(len(working))), ("action", "intersect"))
    return key_value_result(title, data, rows, hints=("vars", "peek"))


_SPEC_ROWS = (
    (
        "feed_events",
        "Feed events",
        FeedEventsOptions,
        _execute_feed_events,
        "reads_state",
        "grid",
    ),
    (
        "feed_seed",
        "Seed set from feed events",
        FeedSeedOptions,
        _execute_feed_seed,
        "mutates_selection",
        "key_value",
    ),
    (
        "efts_search",
        "EFTS full-text search",
        EftsSearchOptions,
        _execute_efts_search,
        "reads_state",
        "grid",
    ),
    (
        "efts_capture",
        "Capture an EFTS search",
        EftsCaptureOptions,
        _execute_efts_capture,
        "external",
        "key_value",
    ),
    (
        "local_search",
        "Local text search",
        LocalSearchOptions,
        _execute_local_search,
        "reads_state",
        "grid",
    ),
    (
        "local_search_seed",
        "Seed set from local search",
        LocalSearchSeedOptions,
        _execute_local_search_seed,
        "mutates_selection",
        "key_value",
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
            result_kind=kind,
            hints=("session_summary",),
            executor=executor,
        )
        for op_id, label, options_type, executor, effect, kind in _SPEC_ROWS
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


def _gather_efts_search(session: Any) -> EftsSearchOptions:
    return _generic(session, EftsSearchOptions)


def _gather_efts_capture(session: Any) -> EftsCaptureOptions:
    return _generic(session, EftsCaptureOptions)


GATHERERS: dict[str, Callable[[Any], Any]] = {
    "feed_events": lambda session: _generic(session, FeedEventsOptions),
    "feed_seed": lambda session: _generic(session, FeedSeedOptions),
    "efts_search": _gather_efts_search,
    "efts_capture": _gather_efts_capture,
    "local_search": lambda session: _generic(session, LocalSearchOptions),
    "local_search_seed": lambda session: _generic(session, LocalSearchSeedOptions),
}
