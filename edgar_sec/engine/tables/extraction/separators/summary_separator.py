"""Statement-summary separator: the S1 priced denial rules.

Evaluates the priced conjunctions (form_signal_specs) over a
table's context surfaces, mirroring the pricing extractor; a
fire marks the geometry a statement summary, not a member.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.form_specs.form_signal_specs import (
    SUMMARY_SEPARATOR_SPECS,
    SummarySeparatorSpec,
)
from edgar_sec.foundation.text.dates import YEAR_TOKEN_SEARCH_RE

_LEAD_CHARS = 1500


@dataclass(frozen=True, slots=True)
class SeparatorFeatures:
    """One table's priced separator features (S1 pricing mirror)."""

    item: str
    hay: str
    years: int
    rows: int
    cols: int
    summar_lead: bool
    has_total_row: bool
    last_stub_total: bool
    nongaap_prose: bool = False


@dataclass(frozen=True, slots=True)
class SummarySeparatorResult:
    """The separator's verdict over one table: the fired rules."""

    rules: tuple[str, ...] = ()
    sub_masses: tuple[str, ...] = ()

    @property
    def fired(self) -> bool:
        """Whether any priced rule fired on the table."""
        return bool(self.rules)

    @property
    def detail(self) -> str:
        """The fired sub-masses and rules, for the gate trail."""
        return f"{'+'.join(self.sub_masses)}: {', '.join(self.rules)}"


def separator_features(table) -> SeparatorFeatures:
    """Extract the priced features from a TypedTable's context."""
    context = table.context
    grid = [
        tuple(cell.strip() for cell in row)
        for row in context.rows
        if any(cell.strip() for cell in row)
    ]
    stubs = [next((cell for cell in row if cell), "") for row in grid]
    caption = " ".join(context.caption_stack)
    lead = (context.prose_before or "")[-_LEAD_CHARS:]
    after_lead = (context.prose_after or "")[:_LEAD_CHARS]
    hay = "; ".join(stubs).lower() + " " + caption.lower() + " " + lead.lower()
    header_text = " ".join(cell for row in grid[:3] for cell in row).lower()
    years = len(set(YEAR_TOKEN_SEARCH_RE.findall(header_text + " " + caption)))
    section = context.section
    item = ((section.item if section else None) or "").strip().upper()
    return SeparatorFeatures(
        item=item,
        hay=hay,
        years=years,
        rows=len(grid),
        cols=max((len(row) for row in grid), default=0),
        summar_lead="summar" in (caption + " " + lead).lower(),
        has_total_row=any(stub.lower().startswith("total") for stub in stubs),
        last_stub_total=bool(stubs) and stubs[-1].lower().startswith("total"),
        nongaap_prose="non-gaap" in (lead + " " + after_lead).lower(),
    )


def _atom_holds(atom: str, features: SeparatorFeatures) -> bool:
    """Evaluate one priced conjunction atom over the features."""
    if atom.startswith("loc_item"):
        return features.item == f"ITEM {atom.removeprefix('loc_item')}"
    if atom.startswith("present["):
        return atom[len("present[") : -1] in features.hay
    if atom.startswith("years>="):
        return features.years >= int(atom.removeprefix("years>="))
    if atom.startswith("rows<="):
        return features.rows <= int(atom.removeprefix("rows<="))
    if atom.startswith("cols<="):
        return features.rows > 0 and features.cols <= int(atom.removeprefix("cols<="))
    if atom == "summar_lead":
        return features.summar_lead
    if atom == "nongaap_prose":
        return features.nongaap_prose
    if atom == "has_total_row":
        return features.has_total_row
    if atom == "last_stub_total":
        return features.last_stub_total
    return False


def evaluate_summary_separator(
    table, specs: tuple[SummarySeparatorSpec, ...] = SUMMARY_SEPARATOR_SPECS
) -> SummarySeparatorResult:
    """Fire the priced rules whose conjunctions the table meets."""
    features = separator_features(table)
    fired = [
        spec
        for spec in specs
        if all(_atom_holds(atom, features) for atom in spec.atoms)
    ]
    return SummarySeparatorResult(
        rules=tuple(spec.rule_id for spec in fired),
        sub_masses=tuple(dict.fromkeys(spec.sub_mass for spec in fired)),
    )
