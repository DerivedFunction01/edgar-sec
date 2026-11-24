"""Company rows: the composite landing and its filings and concept rows.

Name scoring, name resolution, and the frames cross-check home in the
sibling modules beside this one.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from edgar_sec.apps.client.operator.operator_company_frames import _execute_frames
from edgar_sec.apps.client.operator.operator_company_resolution import (
    _cik_text,
    _company_summary,
    _resolve_company,
)
from edgar_sec.apps.client.operator.operator_kit import (
    gather_options as _generic,
    help_field as _f,
    make_build_specs,
    make_module_getattr,
    make_register,
)
from edgar_sec.apps.client.operator.operator_tools import (
    error_result,
    json_native,
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
]


_ID_HELP = "Company identifier: a CIK or ticker resolves directly; a name resolves through scored candidates over the catalog's name data, and a near-tie refuses with the candidates listed rather than picking one."
_INCLUDE_HELP = "Sections to include, drawn from the closed set (profile, recent_filings, financials, facts_cross_check). Any other value is refused. A section that fails is coded beside the sections that succeeded."
_LIMIT_HELP = "Maximum rows shown; total versus shown is declared. Refused below 1."

INCLUDE_SECTIONS = ("profile", "recent_filings", "financials", "facts_cross_check")


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
    from edgar_sec.apps.client.operator.operator_selection import catalog_rows

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
    from edgar_sec.apps.client.operator.operator_execution import OpResult
    from edgar_sec.apps.client.operator.operator_company_facts import (
        facts_check_section,
    )

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
        "facts_cross_check": lambda: facts_check_section(
            company, session, _cik_text(company)
        ),
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
    from edgar_sec.apps.client.operator.operator_execution import OpResult
    from edgar_sec.apps.client.operator.operator_selection import store_working_set

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
    from edgar_sec.apps.client.operator.operator_execution import OpResult

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


build_specs = make_build_specs(_SPEC_ROWS)


register = make_register(build_specs)


__getattr__ = make_module_getattr(build_specs, __name__)


GATHERERS: dict[str, Callable[[Any], Any]] = {
    "company": lambda session: _generic(session, CompanyOptions),
    "company_filings": lambda session: _generic(session, CompanyFilingsOptions),
    "company_concept": lambda session: _generic(session, CompanyConceptOptions),
    "frames": lambda session: _generic(session, FramesOptions),
}
