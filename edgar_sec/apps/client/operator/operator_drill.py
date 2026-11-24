"""Drill-down rows for the client operator: position and current filing.

Rows contribute through ``register(registry)`` and ``GATHERERS``; operator
imports stay inside functions so this module loads standalone.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from edgar_sec.apps.client.operator.operator_drill_access import (
    _absent,
    _capable,
    _current_aggregate,
    _find_aggregate,
    _gate,
    _primary_text,
    _prose,
    _sequence_context,
    _sole_context,
)
from edgar_sec.apps.client.operator.operator_drill_options import (
    DETAIL_LEVELS,
    BackOptions,
    NotesListOptions,
    PrimaryDocumentOptions,
    ReadNoteOptions,
    ReadSectionOptions,
    SectionsListOptions,
    SelectFilingOptions,
    TocOptions,
)
from edgar_sec.apps.client.operator.operator_kit import (
    accession_text as _accession_text,
    error_result as _error,
    key_value_result as _key_value,
    make_module_getattr,
    make_register,
)
from edgar_sec.foundation.runtime.interactive import (
    PickItem,
    prompt_choice,
    prompt_paginated_choice,
    prompt_text,
)
from edgar_sec.foundation.runtime.render import Grid

__all__ = [
    "GATHERERS",
    "SPECS",
    "build_specs",
    "register",
]


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
    from edgar_sec.apps.client.operator.operator_results import OpResult

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
    from edgar_sec.apps.client.operator.operator_results import OpResult

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
    from edgar_sec.apps.client.operator.operator_specs import OperationSpec

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


register = make_register(build_specs)


__getattr__ = make_module_getattr(build_specs, __name__)


_DETAIL_CHOICES = [("minimal", "minimal"), ("standard", "standard"), ("full", "full")]


def _prompt_detail() -> str:
    return prompt_choice("detail", _DETAIL_CHOICES, "standard")


def _prompt_limit(default: int = 20) -> int:
    raw = prompt_text("limit", str(default)).strip()
    return int(raw) if raw.isdigit() else default


def _gather_select(session: Any) -> SelectFilingOptions:
    from edgar_sec.apps.client.operator.operator_selection import catalog_rows

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
