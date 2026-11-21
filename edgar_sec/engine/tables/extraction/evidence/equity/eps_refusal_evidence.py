"""EPS claim refusals: the precision-p3 packet forms.
A claim is refused when a priced form fires over the
geometry's own surfaces; an absent surface never fires.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.form_specs.eps_refusal_specs import (
    EPS_REFUSAL_SPECS_BY_TEST_ID,
    EpsRefusalSpec,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_types import FormTestSpec
from edgar_sec.engine.tables.extraction.core.text.normalize import normalize_text
from edgar_sec.engine.tables.extraction.core.typed_rows import TypedTable

_EPS_TOKEN = re.compile(r"\beps\b")


@dataclass(frozen=True, slots=True)
class EpsRefusalText:
    """One geometry's refusal surfaces, in the shared normal
    form. Prose is the prose_before tail; rows carry their
    first-cell labels and full texts."""

    prose_tail: str = ""
    caption_text: str = ""
    note_text: str = ""
    note_present: bool = False
    caption_present: bool = False
    row_labels: tuple[str, ...] = ()
    row_texts: tuple[str, ...] = ()

    @classmethod
    def from_table(cls, table: TypedTable, tail_chars: int) -> EpsRefusalText:
        """Refusal surfaces from a typed table's context."""
        context = table.context
        note = context.note
        note_text = (
            normalize_text(" ".join(part for part in (note.label, note.title) if part))
            if note
            else ""
        )
        caption_text = normalize_text(" ".join(context.caption_stack))
        labels = []
        row_texts = []
        for row in context.rows:
            label = ""
            texts = []
            for cell in row:
                folded = normalize_text(str(cell))
                if folded:
                    if not label:
                        label = folded
                    texts.append(folded)
            labels.append(label)
            row_texts.append(" ".join(texts))
        prose = context.prose_before or ""
        return cls(
            prose_tail=normalize_text(prose[-tail_chars:]),
            caption_text=caption_text,
            note_text=note_text,
            note_present=bool(note_text),
            caption_present=bool(caption_text),
            row_labels=tuple(labels),
            row_texts=tuple(row_texts),
        )


def _share_row(label: str, spec: EpsRefusalSpec) -> bool:
    """A share-count row under the canonical row vocabulary."""
    if any(phrase in label for phrase in spec.share_phrases):
        return True
    if "weighted" in label and "shares" in label:
        return True
    if "common shares" in label or "common units" in label:
        return any(term in label for term in ("basic", "diluted", "weighted"))
    return False


def _amount_row(label: str, spec: EpsRefusalSpec) -> bool:
    """A per-share amount row under the canonical row vocabulary."""
    return any(phrase in label for phrase in spec.amount_phrases) or bool(
        _EPS_TOKEN.search(label)
    )


@dataclass(frozen=True, slots=True)
class EpsRefusalLegs:
    """The priced forms' leg readings over one geometry."""

    prose_eps: bool
    rows_eps_content: bool
    note_other: bool
    caption_other: bool
    identity_absent: bool
    proforma_hit: bool
    as_reported_hit: bool

    @property
    def adjacency(self) -> bool:
        """P3-1: EPS prose carries the geometry, its own rows
        carry no EPS content, its own identity other or absent."""
        return (
            self.prose_eps
            and not self.rows_eps_content
            and (self.note_other or self.caption_other or self.identity_absent)
        )

    @property
    def proforma(self) -> bool:
        """P3-2: a pro-forma marker over prose, caption, or
        rows, with an as-reported row of its own."""
        return self.proforma_hit and self.as_reported_hit


def legs_for(text: EpsRefusalText, spec: EpsRefusalSpec) -> EpsRefusalLegs:
    """Every leg of the priced refusal forms over one geometry."""
    prose_eps = any(
        phrase in text.prose_tail
        for phrase in spec.identity_phrases + spec.prose_extra_phrases
    )
    rows_eps_content = any(
        _share_row(label, spec) or _amount_row(label, spec) for label in text.row_labels
    )
    note_eps = any(phrase in text.note_text for phrase in spec.identity_phrases)
    caption_eps = any(phrase in text.caption_text for phrase in spec.identity_phrases)
    proforma_hit = any(
        phrase in surface
        for phrase in spec.proforma_phrases
        for surface in (text.prose_tail, text.caption_text, *text.row_texts)
    )
    as_reported_hit = bool(spec.as_reported_phrase) and any(
        spec.as_reported_phrase in label for label in text.row_labels
    )
    return EpsRefusalLegs(
        prose_eps=prose_eps,
        rows_eps_content=rows_eps_content,
        note_other=text.note_present and not note_eps,
        caption_other=text.caption_present and not caption_eps,
        identity_absent=not text.note_present and not text.caption_present,
        proforma_hit=proforma_hit,
        as_reported_hit=as_reported_hit,
    )


@dataclass(frozen=True, slots=True)
class EpsRefusalVerdict:
    """The refusal verdict for one geometry: fired, if any."""

    fired: bool
    evaluable: bool
    legs: EpsRefusalLegs | None
    detail: str


def evaluate_adjacency_refusal(
    text: EpsRefusalText, spec: EpsRefusalSpec
) -> EpsRefusalVerdict:
    """The adjacency refusal alone over one geometry's surfaces."""
    legs = legs_for(text, spec)
    if legs.adjacency:
        return EpsRefusalVerdict(
            True,
            True,
            legs,
            "adjacency form fired: eps prose, "
            "no eps rows, own identity other or absent",
        )
    return EpsRefusalVerdict(False, True, legs, "adjacency form silent")


def evaluate_form_test_eps_adjacency_refusal(
    table: TypedTable, spec: FormTestSpec
) -> EpsRefusalVerdict:
    """Stage adapter: evaluate the adjacency refusal over a table."""
    refusal_spec = EPS_REFUSAL_SPECS_BY_TEST_ID.get(spec.test_id)
    if refusal_spec is None:
        return EpsRefusalVerdict(False, False, None, "no refusal spec for test")
    if not table.context.rows:
        return EpsRefusalVerdict(False, False, None, "no grid rows")
    return evaluate_adjacency_refusal(
        EpsRefusalText.from_table(table, refusal_spec.prose_tail_chars),
        refusal_spec,
    )


def evaluate_proforma_refusal(
    text: EpsRefusalText, spec: EpsRefusalSpec
) -> EpsRefusalVerdict:
    """The pro-forma refusal alone over one geometry's surfaces."""
    legs = legs_for(text, spec)
    if legs.proforma:
        return EpsRefusalVerdict(
            True,
            True,
            legs,
            "proforma form fired: pro forma marker, as reported row",
        )
    return EpsRefusalVerdict(False, True, legs, "proforma form silent")


def evaluate_form_test_eps_proforma_refusal(
    table: TypedTable, spec: FormTestSpec
) -> EpsRefusalVerdict:
    """Stage adapter: evaluate the pro-forma refusal over a table."""
    refusal_spec = EPS_REFUSAL_SPECS_BY_TEST_ID.get(spec.test_id)
    if refusal_spec is None:
        return EpsRefusalVerdict(False, False, None, "no refusal spec for test")
    if not table.context.rows:
        return EpsRefusalVerdict(False, False, None, "no grid rows")
    return evaluate_proforma_refusal(
        EpsRefusalText.from_table(table, refusal_spec.prose_tail_chars),
        refusal_spec,
    )
