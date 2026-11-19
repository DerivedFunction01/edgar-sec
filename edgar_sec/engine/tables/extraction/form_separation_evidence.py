"""Form-separation evidence (TEST_FORM_SEPARATION).

The claim-level form determination over one candidate:
the geometry's determined form read against the family's
foreign classes and gold-routing families.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.form_separation_specs import (
    FORM_SEPARATION_SPECS,
    FormSeparationSpec,
)
from edgar_sec.engine.tables.extraction.pension_routed_evidence import (
    header_keys,
    stub_key,
)

_HEADER_LINES = 3


class FormSeparationText:
    """The packet text surface the determiner reads."""

    def __init__(self, table_text, caption_stack=()):
        lines = [ln for ln in (table_text or "").split("\n") if ln.strip()]
        self.rows = [tuple(c.strip() for c in ln.split("|")) for ln in lines]
        self.raw_stubs = tuple(row[0] for row in self.rows)
        self.stubs = tuple(stub for stub in self.raw_stubs if stub)
        self.headers = tuple(
            cell for row in self.rows[:_HEADER_LINES] for cell in row
        )
        self.caption_stack = list(caption_stack or [])
        self.stub_keys = frozenset(
            key for key in (stub_key(stub) for stub in self.stubs) if key
        )
        self.header_keys = header_keys(self.headers)

    @classmethod
    def from_packet(cls, packet):
        return cls(packet.get("table_text") or "", packet.get("caption_stack") or [])

    @classmethod
    def from_rows(cls, rows, caption_stack=()):
        table_text = "\n".join(" | ".join(str(c) for c in row) for row in rows)
        return cls(table_text, caption_stack)


@dataclass(frozen=True, slots=True)
class FormSeparationVerdict:
    """The determination's read: refused on a foreign form."""

    fired: bool
    evaluable: bool
    legs: tuple[str, ...]
    detail: str


def _determine_form(text: FormSeparationText, spec: FormSeparationSpec) -> str | None:
    """The determined form token for one candidate, or None.

    Derivation point: priced per class on-session against
    the fixed points; consumes the fragment and summary
    recognizers from their homes, never re-derived here.
    """
    raise NotImplementedError("form determiner: derived on-session")


def _is_foreign(token: str, spec: FormSeparationSpec) -> bool:
    """Whether a determined form token refuses this family."""
    if token in spec.foreign_classes:
        return True
    if token == "restatement-recast":
        return spec.recast_cell
    if token.startswith("gold:"):
        return token[len("gold:") :] in spec.gold_families
    if token.startswith("shape:"):
        return spec.foreign_shapes and token[len("shape:") :] != spec.family
    return False


def evaluate_form_separation(
    text: FormSeparationText, spec: FormSeparationSpec
) -> FormSeparationVerdict:
    """Refuse when the determined form is foreign here."""
    if not text.rows:
        return FormSeparationVerdict(False, False, (), "no grid rows")
    token = _determine_form(text, spec)
    if token is None or not _is_foreign(token, spec):
        return FormSeparationVerdict(False, True, (), "form separation clear")
    legs = (f"form:{token}",)
    return FormSeparationVerdict(
        True, True, legs, "form separation fired: " + ", ".join(legs)
    )


# ---------------------------------------------------------------
# Production wiring: the stage adapter reads the assembled
# table's full grid (context rows) through the same derivation.


def evaluate_form_test_form_separation(table, spec) -> FormSeparationVerdict:
    """Stage entry: evaluate the determination over a table."""
    context = table.context
    text = FormSeparationText.from_rows(
        context.rows, list(context.caption_stack) + list(table.caption.titles)
    )
    return evaluate_form_separation(text, FORM_SEPARATION_SPECS[spec.family])
