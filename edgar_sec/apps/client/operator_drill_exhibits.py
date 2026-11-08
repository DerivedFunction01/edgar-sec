"""Exhibit, XBRL, earnings, and save rows for the operator drill-down.

Rows contribute through ``register(registry)`` and ``GATHERERS``; shared
drill helpers live in ``operator_drill``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from edgar_sec.apps.client.operator_drill import (
    DETAIL_LEVELS,
    _PATH_HELP,
    _absent,
    _accession_text,
    _current_aggregate,
    _earnings_capable,
    _error,
    _f,
    _gate,
    _key_value,
    _prompt_detail,
    _prompt_limit,
    _prose,
    _sequence_context,
    _sole_context,
)
from edgar_sec.foundation.runtime.interactive import (
    PickItem,
    prompt_paginated_choice,
    prompt_text,
)
from edgar_sec.foundation.runtime.render import Grid, KeyValueRow, ProseRow

__all__ = [
    "GATHERERS",
    "SPECS",
    "EarningsExhibitOptions",
    "ExhibitsListOptions",
    "ReadExhibitOptions",
    "SaveBundleOptions",
    "SavePayloadOptions",
    "XbrlSummaryOptions",
    "build_specs",
    "register",
]

_LIMIT_HELP = "Maximum rows shown; total versus shown is declared. Refused below 1."
_DETAIL_HELP = "Detail dial (minimal, standard, full): minimal serves the lead block only, standard the complete item text, full the complete text plus its structural context. The dial selects structure, never a character count; any other value is refused."


@dataclass(frozen=True, slots=True)
class ExhibitsListOptions:
    """Options for listing the current filing's exhibits."""

    limit: int = _f(20, _LIMIT_HELP)


@dataclass(frozen=True, slots=True)
class ReadExhibitOptions:
    """Options for reading one exhibit of the current filing."""

    exhibit: str = _f(
        "",
        "Exhibit selector: document type, number, or filename token, "
        "resolved by the aggregate's exhibit accessor.",
    )
    detail: str = _f("standard", _DETAIL_HELP)


@dataclass(frozen=True, slots=True)
class XbrlSummaryOptions:
    """Options for summarising the current filing's XBRL surface."""


@dataclass(frozen=True, slots=True)
class EarningsExhibitOptions:
    """Options for extracting the current filing's earnings exhibit."""


@dataclass(frozen=True, slots=True)
class SavePayloadOptions:
    """Options for saving the current filing's primary payload."""

    path: Path = _f(Path(""), _PATH_HELP)


@dataclass(frozen=True, slots=True)
class SaveBundleOptions:
    """Options for saving the current filing's full submission bundle."""

    path: Path = _f(Path(""), _PATH_HELP)


def _exhibits_list(options: ExhibitsListOptions, session: Any):
    title = "Exhibits"
    if options.limit < 1:
        return _error("grid", "invalid_options", title, "limit below 1")
    aggregate = _current_aggregate(session)
    if aggregate is None:
        return _absent("grid", title, "no filing aggregate is retained")
    exhibits = list(aggregate.exhibits)
    if not exhibits:
        return _absent("grid", title, "the current filing has no exhibits")
    shown = exhibits[: options.limit]
    data_rows = [
        {
            "document_type": str(a.document_type or ""),
            "filename": str(a.filename or ""),
            "description": str(a.description or ""),
            "size": a.size,
        }
        for a in shown
    ]
    from edgar_sec.apps.client.operator import OpResult

    grid = Grid(
        headers=("type", "filename", "description", "size"),
        rows=tuple(
            (r["document_type"], r["filename"], r["description"], str(r["size"] or ""))
            for r in data_rows
        ),
    )
    return OpResult(
        kind="grid",
        title=title,
        components=(grid,),
        data={"exhibits": data_rows, "present": True},
        total=len(exhibits),
        shown=len(data_rows),
        hints=("read_exhibit",),
    )


def _read_exhibit(options: ReadExhibitOptions, session: Any):
    title = "Read exhibit"
    if options.detail not in DETAIL_LEVELS:
        return _error(
            "prose", "invalid_options", title, f"unknown detail: {options.detail}"
        )
    if not options.exhibit.strip():
        return _error(
            "prose", "invalid_options", title, "an exhibit selector is required"
        )
    aggregate = _current_aggregate(session)
    if aggregate is None:
        return _absent("prose", title, "no filing aggregate is retained")
    attachment = aggregate.exhibit(options.exhibit)
    if attachment is None:
        return _error(
            "prose", "not_found", title, f"exhibit not found: {options.exhibit}"
        )
    rendered = attachment.render()
    if rendered is None:
        return _absent("prose", title, "the exhibit has no readable text content")
    text = (
        rendered.decode("utf-8", errors="replace")
        if isinstance(rendered, bytes)
        else str(rendered)
    )
    exhibits = list(aggregate.exhibits)
    index = next((i for i, a in enumerate(exhibits) if a is attachment), 0)
    titled = [
        SimpleNamespace(title=f"{a.document_type} {a.filename}") for a in exhibits
    ]
    context = _sequence_context(titled, index) if exhibits else _sole_context()
    extra = {
        "accession": _accession_text(aggregate),
        "filename": str(attachment.filename),
        "document_type": str(attachment.document_type),
    }
    return _prose(title, text, options.detail, context, extra)


def _statement_titles(xbrl: Any) -> list[str]:
    statements = getattr(xbrl, "statements", None)
    if statements is None:
        return []
    by_category = getattr(statements, "by_category", None)
    if callable(by_category):
        return [str(getattr(e, "title", e)) for e in by_category("statement")]
    list_available = getattr(statements, "list_available", None)
    if callable(list_available):
        frame = list_available()
        records = frame.to_dict("records") if hasattr(frame, "to_dict") else []
        return [
            str(r.get("title", ""))
            for r in records
            if str(r.get("category", "")) == "statement"
        ]
    return []


def _xbrl_summary(options: XbrlSummaryOptions, session: Any):
    title = "XBRL summary"
    gated = _gate(session, "has_xbrl", "key_value", title, "XBRL data")
    if gated is not None:
        return gated
    aggregate = _current_aggregate(session)
    xbrl = session.facade.xbrl(aggregate)
    titles = _statement_titles(xbrl)
    facts = getattr(xbrl, "facts", None)
    fact_count = len(facts) if facts is not None else 0
    data = {
        "accession": _accession_text(aggregate),
        "available": True,
        "present": True,
        "fact_count": fact_count,
        "statements": titles,
        "statement_count": len(titles),
    }
    rows = (
        ("available", "yes"),
        ("facts", str(fact_count)),
        ("statements", str(len(titles))),
        *((f"statement {i + 1}", t) for i, t in enumerate(titles)),
    )
    return _key_value(title, data, rows)


def _earnings(options: EarningsExhibitOptions, session: Any):
    title = "Earnings exhibit"
    aggregate = _current_aggregate(session)
    if aggregate is None:
        return _absent("object", title, "no filing aggregate is retained")
    if not _earnings_capable(session):
        form = str(getattr(aggregate, "form", "") or "")
        return _absent(
            "object",
            title,
            "earnings exhibits are served for current-report filings; "
            f"the current filing is {form}",
            {"accession": _accession_text(aggregate), "form": form},
        )
    result = session.facade.earnings_exhibit(aggregate)
    if getattr(result, "exhibit", None) is None:
        reason = getattr(result, "absence_reason", None) or "no earnings exhibit found"
        return _absent(
            "object", title, str(reason), {"accession": str(result.accession)}
        )
    from edgar_sec.apps.client.operator import OpResult

    exhibit = result.exhibit
    components: list[Any] = [
        KeyValueRow("exhibit", str(exhibit.filename)),
        KeyValueRow("type", str(exhibit.document_type)),
        KeyValueRow("number", str(exhibit.exhibit_number)),
        KeyValueRow("kind", str(exhibit.kind)),
    ]
    figures: dict[str, Any] = {}
    headline = getattr(result, "headline", None)
    for name in ("revenue", "net_income", "eps"):
        figure = getattr(headline, name, None) if headline is not None else None
        if figure is not None:
            figures[name] = {"label": str(figure.label), "value": str(figure.value)}
            components.append(KeyValueRow(str(figure.label), str(figure.value)))
    tables: list[dict[str, Any]] = []
    for table in result.tables:
        rows = [
            {"label": str(r.label), "values": [str(v) for v in r.values]}
            for r in table.rows
        ]
        tables.append(
            {
                "table_index": table.table_index,
                "caption": table.caption,
                "periods": [str(p) for p in table.periods],
                "rows": rows,
            }
        )
        headers = ("label", *table.periods) if table.periods else ("label", "values")
        width = len(headers)
        grid_rows = tuple(
            tuple((r["label"], *r["values"])[:width])
            + ("",) * max(0, width - 1 - len(r["values"]))
            for r in rows
        )
        components.append(Grid(headers=tuple(str(h) for h in headers), rows=grid_rows))
    signals: list[dict[str, Any]] = []
    for signal in result.review_signals:
        entry = {
            "kind": str(signal.kind),
            "filename": str(signal.filename),
            "table_index": signal.table_index,
            "detail": signal.detail,
        }
        signals.append(entry)
        components.append(
            ProseRow(
                f"review: {entry['kind']} {entry['filename']} {entry['detail'] or ''}".rstrip()
            )
        )
    data = {
        "accession": str(result.accession),
        "form": str(result.form),
        "present": True,
        "exhibit": {
            "filename": str(exhibit.filename),
            "document_type": str(exhibit.document_type),
            "exhibit_number": exhibit.exhibit_number,
            "kind": str(exhibit.kind),
        },
        "headline": figures,
        "tables": tables,
        "review_signals": signals,
    }
    return OpResult(
        kind="object",
        title=title,
        components=tuple(components),
        data=data,
        total=len(tables),
        shown=len(tables),
        hints=("read_exhibit", "back"),
    )


def _saves_root(session: Any) -> Path:
    root = getattr(session.facade, "artifacts_root", None)
    if root:
        return Path(root) / "operator-saves"
    from edgar_sec.foundation.runtime.paths import resolve_paths

    return resolve_paths().artifacts_root / "operator-saves"


def _save(options: Any, session: Any, *, bundle: bool):
    title = "Save bundle" if bundle else "Save payload"
    aggregate = _current_aggregate(session)
    if aggregate is None:
        return _absent("key_value", title, "no filing aggregate is retained")
    accession = _accession_text(aggregate)
    if str(options.path) in ("", "."):
        if bundle:
            destination = _saves_root(session) / f"{accession}-bundle.txt"
        else:
            suffix = Path(str(aggregate.primary_document_path or "")).suffix or ".txt"
            destination = _saves_root(session) / f"{accession}-primary{suffix}"
    else:
        destination = Path(options.path)
    try:
        written = (
            aggregate.save_bundle(destination)
            if bundle
            else aggregate.save(destination)
        )
    except FileNotFoundError as exc:
        return _absent("key_value", title, str(exc), {"accession": accession})
    path = Path(written)
    size = path.stat().st_size
    data = {"accession": accession, "path": str(path), "size": size, "present": True}
    rows = (("path", str(path)), ("bytes", str(size)))
    return _key_value(title, data, rows, hints=("back",))


def _save_payload(options: SavePayloadOptions, session: Any):
    return _save(options, session, bundle=False)


def _save_bundle(options: SaveBundleOptions, session: Any):
    return _save(options, session, bundle=True)


_LABELS = {
    "exhibits_list": "List exhibits",
    "read_exhibit": "Read one exhibit",
    "xbrl_summary": "XBRL summary",
    "earnings_exhibit": "Earnings exhibit",
    "save_payload": "Save payload",
    "save_bundle": "Save bundle",
}
_KINDS = {
    "read_exhibit": "prose",
    "exhibits_list": "grid",
    "earnings_exhibit": "object",
}
_SPEC_ROWS = (
    ("exhibits_list", ExhibitsListOptions, _exhibits_list, "reads_state", None),
    ("read_exhibit", ReadExhibitOptions, _read_exhibit, "reads_state", None),
    ("xbrl_summary", XbrlSummaryOptions, _xbrl_summary, "reads_state", "xbrl"),
    ("earnings_exhibit", EarningsExhibitOptions, _earnings, "reads_state", "earnings"),
    ("save_payload", SavePayloadOptions, _save_payload, "external", None),
    ("save_bundle", SaveBundleOptions, _save_bundle, "external", None),
)


def _capable(session: Any) -> bool:
    aggregate = _current_aggregate(session)
    return aggregate is not None and bool(getattr(aggregate, "has_xbrl", False))


def _availability(gate: str | None):
    if gate is None:
        return None
    if gate == "earnings":
        return _earnings_capable
    return lambda session: _capable(session)


def build_specs() -> tuple:
    """Build this module's registry rows; operator imports resolve at call time."""
    from edgar_sec.apps.client.operator import OperationSpec

    specs = []
    for op_id, options_type, executor, effect, gate in _SPEC_ROWS:
        specs.append(
            OperationSpec(
                id=op_id,
                label=_LABELS[op_id],
                options_type=options_type,
                effect=effect,
                requires="current_filing",
                result_kind=_KINDS.get(op_id, "key_value"),
                hints=("session_summary",),
                executor=executor,
                available=_availability(gate),
            )
        )
    return tuple(specs)


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


def _gather_read_exhibit(session: Any) -> ReadExhibitOptions:
    aggregate = _current_aggregate(session)
    exhibits = list(aggregate.exhibits) if aggregate is not None else []
    items = [
        PickItem(
            key=str(a.filename),
            label=f"{a.document_type} {a.filename}".strip(),
            value=str(a.filename),
        )
        for a in exhibits
    ]
    chosen = prompt_paginated_choice(items, prompt_label="Select exhibit")
    return ReadExhibitOptions(
        exhibit=str(chosen.value) if chosen else "", detail=_prompt_detail()
    )


def _gather_save_payload(session: Any) -> SavePayloadOptions:
    return SavePayloadOptions(path=Path(prompt_text("path", "").strip()))


def _gather_save_bundle(session: Any) -> SaveBundleOptions:
    return SaveBundleOptions(path=Path(prompt_text("path", "").strip()))


GATHERERS: dict[str, Callable[[Any], Any]] = {
    "exhibits_list": lambda session: ExhibitsListOptions(limit=_prompt_limit()),
    "read_exhibit": _gather_read_exhibit,
    "xbrl_summary": lambda session: XbrlSummaryOptions(),
    "earnings_exhibit": lambda session: EarningsExhibitOptions(),
    "save_payload": _gather_save_payload,
    "save_bundle": _gather_save_bundle,
}
