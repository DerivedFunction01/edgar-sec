"""Drill-down rows for the client operator: position and current filing.

Rows contribute through ``register(registry)`` and ``GATHERERS``; operator
imports stay inside functions so this module loads standalone.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from edgar_sec.domain.forms.families.current.processing import (
    PROFILE as _CURRENT_PROFILE,
)
from edgar_sec.foundation.runtime.interactive import (
    PickItem,
    prompt_choice,
    prompt_paginated_choice,
    prompt_text,
)
from edgar_sec.foundation.runtime.render import Grid, KeyValueRow, ProseRow

__all__ = [
    "DETAIL_LEVELS",
    "GATHERERS",
    "SPECS",
    "BackOptions",
    "NotesListOptions",
    "PrimaryDocumentOptions",
    "ReadNoteOptions",
    "ReadSectionOptions",
    "SectionsListOptions",
    "SelectFilingOptions",
    "TocOptions",
    "build_specs",
    "register",
]


def _f(default: Any, help_text: str):
    return field(default=default, metadata={"help": help_text})


DETAIL_LEVELS = ("minimal", "standard", "full")
_DETAIL_HELP = "Detail dial (minimal, standard, full): minimal serves the lead block only, standard the complete item text, full the complete text plus its structural context. The dial selects structure, never a character count; any other value is refused."
_LIMIT_HELP = "Maximum rows shown; total versus shown is declared. Refused below 1."
_PATH_HELP = "Destination path; empty writes to the operator-saves area under the facade's artifacts root, and the result reports the path and byte size."


@dataclass(frozen=True, slots=True)
class SelectFilingOptions:
    """Options for moving the drill-down position to one filing."""

    accession: str = _f(
        "",
        "Accession to select from the current set. Refusal: a set retaining "
        "accessions only (no result) is refused, because drill-down needs "
        "the filing aggregates; an accession outside the set is not_found.",
    )


@dataclass(frozen=True, slots=True)
class BackOptions:
    """Options for clearing the drill-down position."""


@dataclass(frozen=True, slots=True)
class PrimaryDocumentOptions:
    """Options for reading the current filing's primary document."""

    detail: str = _f("standard", _DETAIL_HELP)


@dataclass(frozen=True, slots=True)
class SectionsListOptions:
    """Options for listing the current filing's sections."""

    limit: int = _f(20, _LIMIT_HELP)


@dataclass(frozen=True, slots=True)
class ReadSectionOptions:
    """Options for reading one section of the current filing."""

    item: str = _f(
        "", "Section item identifier (e.g. ITEM 1A); an unknown item is not_found."
    )
    detail: str = _f("standard", _DETAIL_HELP)


@dataclass(frozen=True, slots=True)
class NotesListOptions:
    """Options for listing the current filing's notes."""

    limit: int = _f(20, _LIMIT_HELP)


@dataclass(frozen=True, slots=True)
class ReadNoteOptions:
    """Options for reading one note of the current filing."""

    number: int = _f(0, "Note number; an unknown number is not_found.")
    detail: str = _f("standard", _DETAIL_HELP)


@dataclass(frozen=True, slots=True)
class TocOptions:
    """Options for showing the current filing's table of contents span."""


def _error(kind: str, code: str, title: str, message: str, data: dict | None = None):
    from edgar_sec.apps.client.operator import OpResult

    return OpResult(
        kind=kind,
        title=title,
        components=(ProseRow(message),),
        data={**(data or {}), "message": message},
        error_code=code,
    )


def _absent(kind: str, title: str, message: str, data: dict | None = None):
    return _error(kind, "absent", title, message, {**(data or {}), "present": False})


def _key_value(title: str, data: dict, rows: Iterable[tuple[str, str]], **extra: Any):
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


def _accession_text(filing: Any) -> str:
    accession = getattr(filing, "accession", filing)
    return str(getattr(accession, "value", accession))


def _find_aggregate(result: Any, accession: str) -> Any:
    items = getattr(result, "items", None)
    candidates = items
    if candidates is None:
        try:
            candidates = iter(result)
        except TypeError:
            return None
    for filing in candidates:
        if _accession_text(filing) == accession:
            return filing
    return None


def _current_aggregate(session: Any) -> Any:
    """The position's aggregate, falling back to the sets' retained results."""
    filing = getattr(session, "current_filing", None)
    if filing is None:
        return None
    if getattr(filing, "aggregate", None) is not None:
        return filing.aggregate
    for working in session.sets.values():
        if working.result is not None:
            found = _find_aggregate(working.result, filing.accession)
            if found is not None:
                return found
    return None


def _capable(session: Any, flag: str) -> bool:
    aggregate = _current_aggregate(session)
    return aggregate is not None and bool(getattr(aggregate, flag, False))


def _earnings_capable(session: Any) -> bool:
    """Whether the filing's family is the current-report family.

    Keyed on the aggregate's own processing profile, compared against the
    current family's profile, so the operator stays form-agnostic.
    """
    aggregate = _current_aggregate(session)
    if aggregate is None:
        return False
    profile = getattr(aggregate, "processing_profile", None)
    return profile is not None and profile.family == _CURRENT_PROFILE.family


def _gate(session: Any, flag: str, kind: str, title: str, noun: str):
    """An honest-absence result when the current filing lacks a capability."""
    aggregate = _current_aggregate(session)
    if aggregate is None:
        return _absent(
            kind, title, "no filing aggregate is retained for the current filing"
        )
    if not bool(getattr(aggregate, flag, False)):
        form = str(getattr(aggregate, "form", "") or "")
        return _absent(
            kind,
            title,
            f"current filing ({form}) has no {noun}",
            {"accession": _accession_text(aggregate), "form": form},
        )
    return None


def _lead_block(text: str) -> str:
    lines = text.splitlines()
    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1
    block: list[str] = []
    while index < len(lines) and lines[index].strip():
        block.append(lines[index])
        index += 1
    return "\n".join(block)


def _prose(
    title: str,
    text: str,
    detail: str,
    context: dict[str, Any],
    extra: dict[str, Any],
):
    from edgar_sec.apps.client.operator import OpResult

    if detail not in DETAIL_LEVELS:
        return _error(
            "prose", "invalid_options", title, f"unknown detail level: {detail}"
        )
    shown_text = _lead_block(text) if detail == "minimal" else text
    data: dict[str, Any] = {
        **extra,
        "text": shown_text,
        "detail": detail,
        "full_size": len(text),
        "shown_size": len(shown_text),
    }
    components: list[Any] = [ProseRow(shown_text)]
    if detail == "full":
        data["context"] = context
        rows = [("position", f"{context['position']} of {context['total']}")]
        if context.get("previous_title"):
            rows.append(("previous", str(context["previous_title"])))
        if context.get("next_title"):
            rows.append(("next", str(context["next_title"])))
        components.extend(KeyValueRow(k, v) for k, v in rows)
    return OpResult(
        kind="prose",
        title=title,
        components=tuple(components),
        data=data,
        total=1,
        shown=1,
        hints=("back", "select_filing"),
    )


def _sole_context() -> dict[str, Any]:
    return {"position": 1, "total": 1, "previous_title": None, "next_title": None}


def _sequence_context(items: list[Any], index: int) -> dict[str, Any]:
    def title_of(item: Any) -> str | None:
        return str(getattr(item, "title", "") or "") or None

    return {
        "position": index + 1,
        "total": len(items),
        "previous_title": title_of(items[index - 1]) if index > 0 else None,
        "next_title": title_of(items[index + 1]) if index + 1 < len(items) else None,
    }


def _primary_text(aggregate: Any) -> str:
    report = aggregate.as_report()
    text_method = getattr(report, "text", None)
    if callable(text_method):
        text = text_method()
        if text:
            return str(text)
    raw = aggregate.raw()
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        return raw
    rendered = aggregate.render()
    if isinstance(rendered, bytes):
        return rendered.decode("utf-8", errors="replace")
    return str(rendered or "")


def _select_filing(options: SelectFilingOptions, session: Any):
    title = "Select filing"
    accession = options.accession.strip()
    if not accession:
        return _error("key_value", "invalid_options", title, "an accession is required")
    working = session.current_set
    if working is None or accession not in working.accessions:
        return _error(
            "key_value",
            "not_found",
            title,
            f"accession not in current set: {accession}",
        )
    if working.result is None:
        return _error(
            "key_value",
            "refused",
            title,
            "drill-down needs filing aggregates, but the current set retains "
            "accessions only (no retained result)",
            {"accession": accession, "set": session.current_set_name},
        )
    aggregate = _find_aggregate(working.result, accession)
    if aggregate is None:
        return _error(
            "key_value",
            "not_found",
            title,
            f"no aggregate retained for accession: {accession}",
        )
    session.select_filing(accession, aggregate=aggregate)
    data = {
        "accession": accession,
        "form": str(getattr(aggregate, "form", "") or ""),
        "filing_date": str(getattr(aggregate, "filing_date", "") or ""),
        "set": session.current_set_name,
    }
    rows = (
        ("accession", accession),
        ("form", data["form"]),
        ("filing date", data["filing_date"]),
        ("set", data["set"]),
    )
    return _key_value(title, data, rows, hints=("primary_document", "sections_list"))


def _back(options: BackOptions, session: Any):
    cleared = session.current_filing.accession if session.current_filing else ""
    session.clear_filing()
    data = {"cleared": cleared, "current_filing": ""}
    rows = (("cleared", cleared or "none"), ("current filing", "none"))
    return _key_value("Back", data, rows, hints=("select_filing", "session_summary"))


def _primary_document(options: PrimaryDocumentOptions, session: Any):
    title = "Primary document"
    aggregate = _current_aggregate(session)
    if aggregate is None:
        return _absent("prose", title, "no filing aggregate is retained")
    text = _primary_text(aggregate)
    if not text:
        return _absent(
            "prose", title, "the current filing's primary document has no text"
        )
    extra = {"accession": _accession_text(aggregate)}
    return _prose(title, text, options.detail, _sole_context(), extra)


def _sections_list(options: SectionsListOptions, session: Any):
    title = "Sections"
    gated = _gate(session, "has_sections", "grid", title, "sections")
    if gated is not None:
        return gated
    if options.limit < 1:
        return _error("grid", "invalid_options", title, "limit below 1")
    aggregate = _current_aggregate(session)
    sequence = session.facade.sections(aggregate)
    sections = list(getattr(sequence, "sections", ()) or ())
    if not sections:
        return _absent("grid", title, "no sections detected in the current filing")
    shown = sections[: options.limit]
    data_rows = [
        {
            "item": str(s.item_identifier),
            "title": str(s.title or ""),
            "start_line": s.start_line,
            "end_line": s.end_line,
        }
        for s in shown
    ]
    from edgar_sec.apps.client.operator import OpResult

    grid = Grid(
        headers=("item", "title", "start", "end"),
        rows=tuple(
            (r["item"], r["title"], str(r["start_line"]), str(r["end_line"] or ""))
            for r in data_rows
        ),
    )
    return OpResult(
        kind="grid",
        title=title,
        components=(grid,),
        data={"sections": data_rows, "present": True},
        total=len(sections),
        shown=len(data_rows),
        hints=("read_section",),
    )


def _read_section(options: ReadSectionOptions, session: Any):
    title = "Read section"
    gated = _gate(session, "has_sections", "prose", title, "sections")
    if gated is not None:
        return gated
    if options.detail not in DETAIL_LEVELS:
        return _error(
            "prose", "invalid_options", title, f"unknown detail: {options.detail}"
        )
    if not options.item.strip():
        return _error("prose", "invalid_options", title, "a section item is required")
    aggregate = _current_aggregate(session)
    text = session.facade.section(aggregate, options.item)
    if not text:
        return _error("prose", "not_found", title, f"section not found: {options.item}")
    sequence = session.facade.sections(aggregate)
    sections = list(getattr(sequence, "sections", ()) or ())
    found = sequence.get(options.item) if sections else None
    index = next(
        (
            i
            for i, s in enumerate(sections)
            if found is not None and s.item_identifier == found.item_identifier
        ),
        0,
    )
    context = _sequence_context(sections, index) if sections else _sole_context()
    extra = {"accession": _accession_text(aggregate), "item": options.item}
    return _prose(title, str(text), options.detail, context, extra)


def _notes_list(options: NotesListOptions, session: Any):
    title = "Notes"
    gated = _gate(session, "has_notes", "grid", title, "notes")
    if gated is not None:
        return gated
    if options.limit < 1:
        return _error("grid", "invalid_options", title, "limit below 1")
    aggregate = _current_aggregate(session)
    sequence = session.facade.notes(aggregate)
    notes = list(getattr(sequence, "notes", ()) or ())
    if not notes:
        return _absent("grid", title, "no notes detected in the current filing")
    shown = notes[: options.limit]
    data_rows = [
        {
            "number": n.note_number,
            "label": str(n.note_label or ""),
            "title": str(n.title or ""),
            "start_line": n.start_line,
            "end_line": n.end_line,
        }
        for n in shown
    ]
    from edgar_sec.apps.client.operator import OpResult

    grid = Grid(
        headers=("number", "label", "title", "start", "end"),
        rows=tuple(
            (
                str(r["number"]),
                r["label"],
                r["title"],
                str(r["start_line"]),
                str(r["end_line"] or ""),
            )
            for r in data_rows
        ),
    )
    return OpResult(
        kind="grid",
        title=title,
        components=(grid,),
        data={"notes": data_rows, "present": True},
        total=len(notes),
        shown=len(data_rows),
        hints=("read_note",),
    )


def _read_note(options: ReadNoteOptions, session: Any):
    title = "Read note"
    gated = _gate(session, "has_notes", "prose", title, "notes")
    if gated is not None:
        return gated
    if options.detail not in DETAIL_LEVELS:
        return _error(
            "prose", "invalid_options", title, f"unknown detail: {options.detail}"
        )
    if options.number < 1:
        return _error("prose", "invalid_options", title, "a note number is required")
    aggregate = _current_aggregate(session)
    text = session.facade.note(aggregate, options.number)
    if not text:
        return _error("prose", "not_found", title, f"note not found: {options.number}")
    sequence = session.facade.notes(aggregate)
    notes = list(getattr(sequence, "notes", ()) or ())
    index = next((i for i, n in enumerate(notes) if n.note_number == options.number), 0)
    context = _sequence_context(notes, index) if notes else _sole_context()
    extra = {"accession": _accession_text(aggregate), "number": options.number}
    return _prose(title, str(text), options.detail, context, extra)


def _toc(options: TocOptions, session: Any):
    title = "Table of contents"
    gated = _gate(session, "has_toc", "key_value", title, "table of contents")
    if gated is not None:
        return gated
    aggregate = _current_aggregate(session)
    span = session.facade.toc(aggregate)
    if span is None:
        return _absent(
            "key_value", title, "no table of contents detected in the current filing"
        )
    data = {
        "start_line": span.start_line,
        "end_line": span.end_line,
        "start_offset": span.start_offset,
        "end_offset": span.end_offset,
        "method": str(span.method),
        "confidence": span.confidence,
        "approximate": bool(span.approximate),
        "present": True,
    }
    rows = (
        ("start line", str(span.start_line)),
        ("end line", str(span.end_line)),
        ("method", str(span.method)),
        ("confidence", str(span.confidence)),
        ("approximate", str(bool(span.approximate))),
    )
    return _key_value(title, data, rows, hints=("sections_list",))


_LABELS = {
    "select_filing": "Select filing",
    "back": "Back (clear filing)",
    "primary_document": "Primary document text",
    "sections_list": "List sections",
    "read_section": "Read one section",
    "notes_list": "List notes",
    "read_note": "Read one note",
    "filing_toc": "Table of contents",
}
_KINDS = {
    "primary_document": "prose",
    "read_section": "prose",
    "read_note": "prose",
    "sections_list": "grid",
    "notes_list": "grid",
}
_SPEC_ROWS = (
    (
        "select_filing",
        SelectFilingOptions,
        _select_filing,
        "moves_position",
        "selection",
        None,
    ),
    ("back", BackOptions, _back, "moves_position", "current_filing", None),
    (
        "primary_document",
        PrimaryDocumentOptions,
        _primary_document,
        "reads_state",
        "current_filing",
        None,
    ),
    (
        "sections_list",
        SectionsListOptions,
        _sections_list,
        "reads_state",
        "current_filing",
        "has_sections",
    ),
    (
        "read_section",
        ReadSectionOptions,
        _read_section,
        "reads_state",
        "current_filing",
        "has_sections",
    ),
    (
        "notes_list",
        NotesListOptions,
        _notes_list,
        "reads_state",
        "current_filing",
        "has_notes",
    ),
    (
        "read_note",
        ReadNoteOptions,
        _read_note,
        "reads_state",
        "current_filing",
        "has_notes",
    ),
    ("filing_toc", TocOptions, _toc, "reads_state", "current_filing", "has_toc"),
)


def _availability(gate: str | None):
    if gate is None:
        return None
    return lambda session: _capable(session, gate)


def build_specs() -> tuple:
    """Build this module's registry rows; operator imports resolve at call time."""
    from edgar_sec.apps.client.operator import OperationSpec

    specs = []
    for op_id, options_type, executor, effect, requires, gate in _SPEC_ROWS:
        specs.append(
            OperationSpec(
                id=op_id,
                label=_LABELS[op_id],
                options_type=options_type,
                effect=effect,
                requires=requires,
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


_DETAIL_CHOICES = [("minimal", "minimal"), ("standard", "standard"), ("full", "full")]


def _prompt_detail() -> str:
    return prompt_choice("detail", _DETAIL_CHOICES, "standard")


def _prompt_limit(default: int = 20) -> int:
    raw = prompt_text("limit", str(default)).strip()
    return int(raw) if raw.isdigit() else default


def _gather_select(session: Any) -> SelectFilingOptions:
    from edgar_sec.apps.client.operator_selection import catalog_rows

    working = session.current_set
    if working is None:
        return SelectFilingOptions()
    if working.result is not None:
        labels = {
            str(r["accession"]): (
                f"{r['accession']} {r.get('form', '')} {r.get('filing_date', '')}".strip()
            )
            for r in catalog_rows(working.result)
            if r.get("accession")
        }
    else:
        labels = {a: a for a in sorted(working.accessions)}
    items = [PickItem(key=a, label=label, value=a) for a, label in labels.items()]
    chosen = prompt_paginated_choice(items, prompt_label="Select filing")
    return SelectFilingOptions(accession=str(chosen.value) if chosen else "")


def _gather_primary(session: Any) -> PrimaryDocumentOptions:
    return PrimaryDocumentOptions(detail=_prompt_detail())


def _gather_read_section(session: Any) -> ReadSectionOptions:
    aggregate = _current_aggregate(session)
    sequence = session.facade.sections(aggregate) if aggregate is not None else None
    sections = list(getattr(sequence, "sections", ()) or ())
    items = [
        PickItem(
            key=str(s.item_identifier),
            label=f"{s.item_identifier} {s.title}".strip(),
            value=str(s.item_identifier),
        )
        for s in sections
    ]
    chosen = prompt_paginated_choice(items, prompt_label="Select section")
    return ReadSectionOptions(
        item=str(chosen.value) if chosen else "", detail=_prompt_detail()
    )


def _gather_read_note(session: Any) -> ReadNoteOptions:
    aggregate = _current_aggregate(session)
    sequence = session.facade.notes(aggregate) if aggregate is not None else None
    notes = list(getattr(sequence, "notes", ()) or ())
    items = [
        PickItem(
            key=str(n.note_number),
            label=f"{n.note_label} {n.title}".strip(),
            value=n.note_number,
        )
        for n in notes
    ]
    chosen = prompt_paginated_choice(items, prompt_label="Select note")
    return ReadNoteOptions(
        number=int(chosen.value) if chosen else 0, detail=_prompt_detail()
    )


GATHERERS: dict[str, Callable[[Any], Any]] = {
    "select_filing": _gather_select,
    "back": lambda session: BackOptions(),
    "primary_document": _gather_primary,
    "sections_list": lambda session: SectionsListOptions(limit=_prompt_limit()),
    "read_section": _gather_read_section,
    "notes_list": lambda session: NotesListOptions(limit=_prompt_limit()),
    "read_note": _gather_read_note,
    "filing_toc": lambda session: TocOptions(),
}
