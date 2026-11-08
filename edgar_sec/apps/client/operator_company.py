"""Company rows and the frames cross-check for the client operator.

Name resolution is closed here, at the operation layer: scored candidates
over the catalog's name data, an exact or clear winner resolving, a
near-tie refusing with the candidates listed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any

from edgar_sec.apps.client.operator_tools import (
    empty_accounting,
    error_result,
    json_native,
    record_external_run,
)
from edgar_sec.foundation.runtime.render import Grid, ProseRow

__all__ = [
    "GATHERERS",
    "SPECS",
    "CompanyConceptOptions",
    "CompanyFilingsOptions",
    "CompanyOptions",
    "FramesOptions",
    "build_specs",
    "register",
    "score_name_candidates",
]


def _f(default: Any, help_text: str):
    return field(default=default, metadata={"help": help_text})


_ID_HELP = "Company identifier: a CIK or ticker resolves directly; a name resolves through scored candidates over the catalog's name data, and a near-tie refuses with the candidates listed rather than picking one."
_INCLUDE_HELP = "Sections to include, drawn from the closed set (profile, recent_filings, financials). Any other value is refused. A section that fails is coded beside the sections that succeeded."
_LIMIT_HELP = "Maximum rows shown; total versus shown is declared. Refused below 1."

INCLUDE_SECTIONS = ("profile", "recent_filings", "financials")
_SCORE_THRESHOLD = 0.6
_SCORE_MARGIN = 0.15
_EXACT_SCORE = 0.98
_SUFFIX_TOKENS = frozenset(
    {
        "inc",
        "corp",
        "corporation",
        "company",
        "co",
        "ltd",
        "llc",
        "plc",
        "lp",
        "sa",
        "nv",
        "ag",
        "holdings",
        "holding",
        "group",
        "the",
        "and",
        "of",
    }
)


@dataclass(frozen=True, slots=True)
class CompanyOptions:
    """Options for the composite company landing."""

    identifier: str = _f("", _ID_HELP)
    include: tuple[str, ...] = _f(INCLUDE_SECTIONS, _INCLUDE_HELP)
    filings_limit: int = _f(10, "Caps the recent-filings section. Refused below 1.")


@dataclass(frozen=True, slots=True)
class CompanyFilingsOptions:
    """Options for one company's filings, seedable into a named set."""

    identifier: str = _f("", _ID_HELP)
    forms: tuple[str, ...] = _f((), "Narrows the filings by form type.")
    dates: str | None = _f(None, "Narrows the filings by date selection.")
    limit: int = _f(10, _LIMIT_HELP)
    into: str = _f(
        "",
        "When set, the filings result is also stored as this named set; "
        "empty returns the grid without seeding.",
    )


@dataclass(frozen=True, slots=True)
class CompanyConceptOptions:
    """Options for one concept lookup in explicit taxonomy/tag coordinates."""

    identifier: str = _f("", _ID_HELP)
    taxonomy: str = _f(
        "",
        "Concept taxonomy (e.g. us-gaap); explicit coordinates only, "
        "never a friendly-name match.",
    )
    tag: str = _f("", "Concept tag in the named taxonomy (e.g. Revenues in us-gaap).")
    limit: int = _f(50, _LIMIT_HELP)


@dataclass(frozen=True, slots=True)
class FramesOptions:
    """Options for one frames cross-check, in explicit frame coordinates."""

    taxonomy: str = _f(
        "",
        "Frame taxonomy (e.g. us-gaap); all four coordinates are "
        "required, none is inferred.",
    )
    tag: str = _f(
        "",
        "Frame concept tag (e.g. Revenues in us-gaap); explicit "
        "taxonomy/tag coordinates only.",
    )
    unit: str = _f("", "Frame unit (e.g. USD).")
    period: str = _f(
        "",
        "Frame period (e.g. CY2024 for a calendar-year duration, "
        "CY2024Q4I for an instant).",
    )
    limit: int = _f(20, _LIMIT_HELP)


def _normalize(text: str) -> tuple[str, frozenset[str]]:
    cleaned = "".join(ch if ch.isalnum() else " " for ch in text.casefold())
    words = cleaned.split()
    tokens = frozenset(word for word in words if word not in _SUFFIX_TOKENS)
    return " ".join(words), tokens


def _score(
    query_norm: str,
    query_tokens: frozenset,
    entry_norm: str,
    entry_tokens: frozenset,
) -> float:
    if query_norm and query_norm == entry_norm:
        return 1.0
    if query_tokens and query_tokens == entry_tokens:
        return _EXACT_SCORE
    score = 0.0
    if query_tokens and entry_tokens:
        common = len(query_tokens & entry_tokens)
        if common:
            score = max(score, common / len(query_tokens | entry_tokens))
            if query_tokens <= entry_tokens or entry_tokens <= query_tokens:
                ratio = min(len(query_tokens), len(entry_tokens)) / max(
                    len(query_tokens), len(entry_tokens)
                )
                score = max(score, 0.8 + 0.15 * ratio)
    if query_norm and entry_norm:
        if query_norm in entry_norm or entry_norm in query_norm:
            score = max(score, 0.85)
        ratio = SequenceMatcher(None, query_norm, entry_norm).ratio()
        score = max(score, ratio * 0.92)
    return round(min(score, 0.97), 4)


def _entry_parts(entry: Any) -> tuple[str, str, list[str]]:
    if isinstance(entry, dict):
        raw_name = entry.get("name", "")
        raw_cik = entry.get("cik", "")
        raw_tickers = entry.get("tickers", ()) or ()
    else:
        raw_name = getattr(entry, "name", "")
        raw_cik = getattr(entry, "cik", "")
        raw_tickers = getattr(entry, "tickers", ()) or ()
    cik = getattr(raw_cik, "value", raw_cik)
    return str(raw_name), str(cik), [str(t) for t in raw_tickers]


def _entry_dict(entry: Any) -> dict[str, Any]:
    entry_name, cik, tickers = _entry_parts(entry)
    return {"name": entry_name, "cik": cik, "tickers": tickers}


def score_name_candidates(query: str, entries: Any) -> list[dict[str, Any]]:
    """Score catalog name entries against ``query``, best first."""
    query_norm, query_tokens = _normalize(query)
    scored: list[dict[str, Any]] = []
    for entry in entries:
        entry_name, cik, tickers = _entry_parts(entry)
        if not entry_name:
            continue
        entry_norm, entry_tokens = _normalize(entry_name)
        value = _score(query_norm, query_tokens, entry_norm, entry_tokens)
        if value > 0:
            scored.append(
                {"name": entry_name, "cik": cik, "tickers": tickers, "score": value}
            )
    scored.sort(key=lambda item: (-item["score"], item["name"], item["cik"]))
    return scored[:10]


def _catalog_entries(session: Any, query: str) -> list[dict[str, Any]]:
    """Name entries from the landed catalog's company-profiles snapshot.

    The same profiles parquet the facade resolver reads; a SQL prefilter
    on the query's longest token bounds what reaches Python scoring.
    """
    facade = session.facade
    for attribute in (
        "company_candidates",
        "name_candidates",
        "company_name_candidates",
    ):
        provider = getattr(facade, attribute, None)
        if callable(provider):
            try:
                return [_entry_dict(item) for item in provider(query)]
            except TypeError:
                return [_entry_dict(item) for item in provider()]
    artifacts = getattr(facade, "artifacts_root", None)
    if not artifacts:
        return []
    try:
        from edgar_sec.infra.storage.duckdb import connect
        from edgar_sec.pipelines.filing_catalog.paths import (
            SNAPSHOT_FILE,
            resolve_filing_catalog_paths,
        )

        paths = resolve_filing_catalog_paths(artifacts)
        if not list(paths.snapshots_root.glob(f"**/{SNAPSHOT_FILE}")):
            return []
        pattern = str(paths.snapshots_root / "**" / SNAPSHOT_FILE)
        tokens = [word for word in _normalize(query)[0].split() if len(word) >= 3]
        token = max(tokens, key=len) if tokens else query.strip()
        sql = (
            "SELECT cik, identity, listings FROM read_parquet(?) "
            "WHERE upper(identity.name) LIKE '%' || upper(?) || '%' LIMIT 500"
        )
        with connect() as con:
            rows = con.execute(sql, [pattern, token]).fetchall()
    except Exception:  # noqa: BLE001 - no readable catalog reads as no candidates
        return []
    entries: list[dict[str, Any]] = []
    for cik, identity, listings in rows:
        identity = identity or {}
        entries.append(
            {
                "name": str(identity.get("name") or ""),
                "cik": str(cik),
                "tickers": [
                    str(item["ticker"])
                    for item in (listings or ())
                    if isinstance(item, dict) and "ticker" in item
                ],
            }
        )
    return entries


def _cik_text(company: Any) -> str:
    cik = getattr(company, "cik", None)
    if cik is None:
        profile = getattr(company, "profile", None)
        cik = getattr(profile, "cik", None)
    to_10digit = getattr(cik, "to_10digit", None)
    if callable(to_10digit):
        return str(to_10digit())
    value = getattr(cik, "value", cik)
    return str(value) if value is not None else ""


def _is_placeholder(company: Any, identifier: str) -> bool:
    """The resolver's unresolved-name placeholder: CIK 1 named as the query."""
    profile = getattr(company, "profile", None)
    cik = getattr(profile, "cik", None)
    value = getattr(cik, "value", cik)
    return value in (1, "1") and str(getattr(profile, "name", "")) == identifier


def _company_summary(company: Any) -> dict[str, Any]:
    return {
        "name": str(getattr(company, "name", "") or ""),
        "cik": _cik_text(company),
        "tickers": [str(t) for t in (getattr(company, "tickers", ()) or ())],
    }


def _resolve_company(session: Any, identifier: str, kind: str):
    """Resolve to (company, resolution, error); exactly one of company/error."""
    title = "Company"
    ident = identifier.strip()
    if not ident:
        return (
            None,
            {},
            error_result(kind, "refused", title, "company refused: no identifier"),
        )
    facade = session.facade
    if ident.isdigit():
        return facade.company(ident), {"via": "cik", "identifier": ident}, None
    try:
        direct = facade.company(ident)
    except Exception:  # noqa: BLE001 - an unresolvable ticker falls to names
        direct = None
    if direct is not None and not _is_placeholder(direct, ident):
        return direct, {"via": "ticker", "identifier": ident}, None
    candidates = score_name_candidates(ident, _catalog_entries(session, ident))
    resolution = {"via": "name", "identifier": ident, "candidates": candidates}
    if not candidates or candidates[0]["score"] < _SCORE_THRESHOLD:
        return (
            None,
            resolution,
            error_result(
                kind,
                "not_found",
                title,
                f"no company name matches: {ident}",
                {"candidates": candidates},
            ),
        )
    top = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    exact_clear = top["score"] >= _EXACT_SCORE and (
        second is None or second["score"] < top["score"]
    )
    margin_clear = second is None or top["score"] - second["score"] >= _SCORE_MARGIN
    if not (exact_clear or margin_clear):
        return (
            None,
            resolution,
            error_result(
                kind,
                "refused",
                title,
                f"name is ambiguous: {ident}; refusing to pick between candidates",
                {"candidates": candidates},
            ),
        )
    return facade.company(top["cik"]), resolution, None


def _profile_section(company: Any) -> dict[str, Any]:
    profile = getattr(company, "profile", None)

    def pick(attribute: str) -> Any:
        value = getattr(company, attribute, None)
        return value if value is not None else getattr(profile, attribute, None)

    return {
        "name": str(pick("name") or ""),
        "cik": _cik_text(company),
        "tickers": [str(t) for t in (pick("tickers") or ())],
        "sic": pick("sic") or pick("sic_code"),
        "sic_description": pick("sic_description"),
        "state_of_incorporation": pick("state_of_incorporation"),
        "fiscal_year_end": pick("fiscal_year_end"),
    }


def _filing_rows(result: Any) -> list[dict[str, Any]]:
    from edgar_sec.apps.client.operator_selection import catalog_rows

    return [
        {
            "accession": str(r["accession"]),
            "form": str(r.get("form") or ""),
            "filing_date": str(r.get("filing_date") or ""),
        }
        for r in catalog_rows(result)
        if r.get("accession")
    ]


def _filings_section(company: Any, limit: int) -> dict[str, Any]:
    rows = _filing_rows(company.filings(limit=limit))
    return {"total": len(rows), "shown": len(rows), "rows": rows}


def _financials_section(company: Any) -> dict[str, Any]:
    probe = getattr(company, "financials_available", None)
    if isinstance(probe, bool):
        return {"available": probe}
    xbrl_fn = getattr(company, "xbrl", None)
    if callable(xbrl_fn):
        surface = xbrl_fn()
        if surface is None:
            return {"available": False}
        return {
            "available": True,
            "surface": type(surface).__name__,
            "has_financials": hasattr(surface, "financials"),
        }
    return {"available": False, "reason": "company offers no xbrl surface"}


def _execute_company(options: CompanyOptions, session: Any):
    from edgar_sec.apps.client.operator import OpResult

    title = "Company"
    unknown = [name for name in options.include if name not in INCLUDE_SECTIONS]
    if unknown:
        return error_result(
            "object",
            "invalid_options",
            title,
            f"unknown include section(s): {', '.join(unknown)}; "
            f"allowed: {', '.join(INCLUDE_SECTIONS)}",
        )
    if options.filings_limit < 1:
        return error_result("object", "invalid_options", title, "filings_limit below 1")
    company, resolution, failure = _resolve_company(
        session, options.identifier, "object"
    )
    if failure is not None:
        return failure
    builders = {
        "profile": lambda: _profile_section(company),
        "recent_filings": lambda: _filings_section(company, options.filings_limit),
        "financials": lambda: _financials_section(company),
    }
    sections: dict[str, Any] = {}
    for name in dict.fromkeys(options.include):
        try:
            sections[name] = {"status": "ok", **builders[name]()}
        except Exception as exc:  # noqa: BLE001 - a failed section is coded beside the rest
            sections[name] = {
                "status": "error",
                "error_code": "external_failure",
                "message": str(exc),
            }
    summary = _company_summary(company)
    components = [
        ProseRow(f"resolved via: {resolution.get('via', '')}"),
        ProseRow(f"cik: {summary['cik']}"),
        ProseRow(f"name: {summary['name']}"),
    ]
    components.extend(
        ProseRow(f"section {name}: {section['status']}")
        for name, section in sections.items()
    )
    data = {
        "identifier": options.identifier,
        "resolution": json_native(resolution),
        "company": summary,
        "sections": sections,
        "include": list(dict.fromkeys(options.include)),
    }
    return OpResult(
        kind="object",
        title=title,
        components=tuple(components),
        data=data,
        total=len(sections),
        shown=len(sections),
        hints=("company_filings", "company_concept"),
    )


def _execute_company_filings(options: CompanyFilingsOptions, session: Any):
    from edgar_sec.apps.client.operator import OpResult
    from edgar_sec.apps.client.operator_selection import store_working_set

    title = "Company filings"
    if options.limit < 1:
        return error_result("grid", "invalid_options", title, "limit below 1")
    company, resolution, failure = _resolve_company(session, options.identifier, "grid")
    if failure is not None:
        return failure
    result = company.filings(
        forms=tuple(options.forms) or None, limit=options.limit, dates=options.dates
    )
    rows = _filing_rows(result)
    data: dict[str, Any] = {
        "company": _company_summary(company),
        "resolution": json_native(resolution),
        "rows": rows,
    }
    if options.into:
        working = store_working_set(session, options.into, result=result)
        data["set"] = options.into
        data["count"] = len(working)
    grid = Grid(
        headers=("accession", "form", "filing_date"),
        rows=tuple((r["accession"], r["form"], r["filing_date"]) for r in rows),
    )
    return OpResult(
        kind="grid",
        title=title,
        components=(grid,),
        data=data,
        total=len(rows),
        shown=len(rows),
        hints=("vars", "peek"),
    )


def _execute_company_concept(options: CompanyConceptOptions, session: Any):
    from edgar_sec.apps.client.operator import OpResult

    title = "Company concept"
    if not (options.taxonomy and options.tag):
        return error_result(
            "grid",
            "invalid_options",
            title,
            "concept lookup needs explicit taxonomy and tag coordinates",
        )
    if options.limit < 1:
        return error_result("grid", "invalid_options", title, "limit below 1")
    company, resolution, failure = _resolve_company(session, options.identifier, "grid")
    if failure is not None:
        return failure
    values = company.concept(options.taxonomy, options.tag)
    rows = [
        {
            "value": value.value,
            "unit": str(value.unit),
            "end": str(value.end),
            "accession": str(value.accession),
            "form": str(value.form),
            "filed": str(value.filed),
            "fiscal_year": value.fiscal_year,
            "fiscal_period": str(value.fiscal_period),
            "frame": str(value.frame),
        }
        for value in values
    ]
    data = {
        "company": _company_summary(company),
        "resolution": json_native(resolution),
        "taxonomy": options.taxonomy,
        "tag": options.tag,
        "provenance": "SEC-reported, exactly as reported",
        "values": rows[: options.limit],
        "present": bool(rows),
    }
    if not rows:
        return OpResult(
            kind="grid",
            title=title,
            components=(ProseRow("no values reported for this concept"),),
            data=data,
            total=0,
            shown=0,
            error_code="absent",
        )
    shown = rows[: options.limit]
    grid = Grid(
        headers=("value", "unit", "end", "accession", "form", "filed"),
        rows=tuple(
            (
                str(r["value"]),
                r["unit"],
                r["end"],
                r["accession"],
                r["form"],
                r["filed"],
            )
            for r in shown
        ),
    )
    return OpResult(
        kind="grid",
        title=title,
        components=(grid,),
        data=data,
        total=len(rows),
        shown=len(shown),
        hints=("frames",),
    )


def _execute_frames(options: FramesOptions, session: Any):
    from edgar_sec.apps.client import operator_run_records as records
    from edgar_sec.apps.client.operator import OpResult

    title = (
        f"Frames cross-check: {options.taxonomy}:{options.tag} "
        f"({options.unit}, {options.period})"
    )
    if not (options.taxonomy and options.tag and options.unit and options.period):
        return error_result(
            "grid",
            "invalid_options",
            title,
            "frames needs explicit taxonomy, tag, unit, and period coordinates",
        )
    if options.limit < 1:
        return error_result("grid", "invalid_options", title, "limit below 1")
    started = datetime.now(UTC)
    cache_before = records.cache_stats(session)
    selection = {
        "kind": "frame",
        "taxonomy": options.taxonomy,
        "tag": options.tag,
        "unit": options.unit,
        "period": options.period,
    }
    try:
        result = session.facade.frames(
            options.taxonomy, options.tag, options.unit, options.period
        )
    except Exception as exc:  # noqa: BLE001 - a facade failure is a coded result
        record_id, _ = record_external_run(
            session,
            operation="frames",
            options_data=asdict(options),
            selection=selection,
            started=started,
            cache_before=cache_before,
            engine="frames",
            result_info={"label": "", "row_count": 0},
            accounting=empty_accounting("facade call raised before any result"),
            error_code="external_failure",
            error=str(exc),
        )
        return error_result(
            "grid", "external_failure", title, str(exc), {"record_id": record_id}
        )
    all_rows = [
        {
            "cik": int(row.cik),
            "entity_name": str(row.entity_name),
            "value": row.value,
            "end": str(row.end),
        }
        for row in result.rows
    ]
    accounting = records.member_accounting([str(r["cik"]) for r in all_rows], None)
    record_id, _ = record_external_run(
        session,
        operation="frames",
        options_data=asdict(options),
        selection=selection,
        started=started,
        cache_before=cache_before,
        engine="frames",
        result_info={"label": str(result.label), "row_count": len(all_rows)},
        accounting=accounting,
    )
    shown = all_rows[: options.limit]
    data = {
        "cross_check": True,
        "provenance": "SEC frame aggregates",
        "frame": {
            "taxonomy": options.taxonomy,
            "tag": options.tag,
            "unit": options.unit,
            "period": options.period,
        },
        "label": str(result.label),
        "rows": shown,
        "record_id": record_id,
        "present": bool(all_rows),
    }
    if not all_rows:
        return OpResult(
            kind="grid",
            title=title,
            components=(ProseRow("frame absent: the SEC frame has no rows"),),
            data=data,
            total=0,
            shown=0,
            error_code="absent",
            hints=("company_concept",),
        )
    grid = Grid(
        headers=("cik", "entity", "value", "end"),
        rows=tuple(
            (str(r["cik"]), r["entity_name"], str(r["value"]), r["end"]) for r in shown
        ),
    )
    return OpResult(
        kind="grid",
        title=title,
        components=(grid,),
        data=data,
        total=len(all_rows),
        shown=len(shown),
        hints=("company_concept",),
    )


_SPEC_ROWS = (
    (
        "company",
        "Company (composite)",
        CompanyOptions,
        _execute_company,
        "reads_state",
        "object",
    ),
    (
        "company_filings",
        "Company filings",
        CompanyFilingsOptions,
        _execute_company_filings,
        "reads_state",
        "grid",
    ),
    (
        "company_concept",
        "Company concept",
        CompanyConceptOptions,
        _execute_company_concept,
        "reads_state",
        "grid",
    ),
    (
        "frames",
        "Frames cross-check",
        FramesOptions,
        _execute_frames,
        "external",
        "grid",
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


GATHERERS: dict[str, Callable[[Any], Any]] = {
    "company": lambda session: _generic(session, CompanyOptions),
    "company_filings": lambda session: _generic(session, CompanyFilingsOptions),
    "company_concept": lambda session: _generic(session, CompanyConceptOptions),
    "frames": lambda session: _generic(session, FramesOptions),
}
