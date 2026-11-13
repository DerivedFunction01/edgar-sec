"""One geometry plus the context evidence the corpus attaches to it."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.ascii_html.model import TableGeometry


@dataclass(frozen=True, slots=True)
class Scale:
    """A stated scale: the caption phrase and its unit."""

    phrase: str
    unit: str


@dataclass(frozen=True, slots=True)
class SectionRef:
    """The form section a table sits in, when one was detected."""

    item: str | None
    title: str | None


@dataclass(frozen=True, slots=True)
class NoteRef:
    """The financial-statements note a table sits in, when detected."""

    number: int | None
    label: str | None
    title: str | None


@dataclass(frozen=True, slots=True)
class LabelRef:
    """The corpus label a geometry carries, verbatim from adjudication."""

    family: str | None
    aligned_family: str | None
    split: str | None
    provenance: str | None
    audited: bool = False


@dataclass(frozen=True, slots=True)
class BreakRef:
    """One page-artifact token in the annotated text frame."""

    line: int
    token: str
    artifact_id: int
    namespace: str | None
    page_number: int | None


@dataclass(frozen=True, slots=True)
class BreakEvidence:
    """Break tokens inside a table's span and at its edges."""

    inside: tuple[BreakRef, ...] = ()
    before: BreakRef | None = None
    after: BreakRef | None = None


@dataclass(frozen=True, slots=True)
class TableContext:
    """A geometry with its caption, location, prose, and break context."""

    geometry: TableGeometry
    caption_stack: tuple[str, ...] = ()
    scale: Scale | None = None
    location: tuple[int, int] | None = None
    section: SectionRef | None = None
    note: NoteRef | None = None
    prose_before: str = ""
    prose_after: str = ""
    breaks: BreakEvidence = BreakEvidence()
    issues: tuple[str, ...] = ()
    label: LabelRef | None = None
    region: str | None = None

    @property
    def table_index(self) -> int:
        return self.geometry.table_index

    @property
    def rows(self) -> tuple[tuple[str, ...], ...]:
        return self.geometry.rows

    @classmethod
    def from_record(cls, geometry: TableGeometry, record: dict) -> TableContext:
        """Build a context from one successor-corpus geometry record."""
        preceding = record.get("preceding") or {}
        section = preceding.get("section")
        note = preceding.get("note")
        scale = record.get("scale")
        location = record.get("location")
        label = record.get("label")
        breaks = record.get("breaks") or {}

        def break_ref(item: dict | None) -> BreakRef | None:
            if item is None:
                return None
            return BreakRef(
                line=item["line"],
                token=item["token"],
                artifact_id=item["id"],
                namespace=item.get("namespace"),
                page_number=item.get("page_number"),
            )

        return cls(
            geometry=geometry,
            caption_stack=tuple(record.get("caption_stack") or ()),
            scale=Scale(scale["phrase"], scale["unit"]) if scale else None,
            location=(location["start_line"], location["end_line"])
            if location
            else None,
            section=SectionRef(section.get("item"), section.get("title"))
            if section
            else None,
            note=NoteRef(note.get("number"), note.get("label"), note.get("title"))
            if note
            else None,
            prose_before=record.get("prose_before") or "",
            prose_after=record.get("prose_after") or "",
            breaks=BreakEvidence(
                inside=tuple(
                    ref
                    for ref in (break_ref(item) for item in breaks.get("inside") or ())
                    if ref is not None
                ),
                before=break_ref(breaks.get("before")),
                after=break_ref(breaks.get("after")),
            ),
            issues=tuple(record.get("issues") or ()),
            label=LabelRef(
                family=label.get("final_family"),
                aligned_family=label.get("aligned_family"),
                split=label.get("split"),
                provenance=label.get("provenance"),
                audited=bool(label.get("audited")),
            )
            if label
            else None,
            region=record.get("region"),
        )
