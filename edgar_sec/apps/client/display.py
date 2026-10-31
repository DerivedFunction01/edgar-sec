"""Display primitives shared by the ASCII and markdown renderers.

Value scaling, label humanization and wrapping, and the filing
identity header live here so every render surface formats alike.
"""

from __future__ import annotations

import textwrap
from collections.abc import Iterable

from edgar_sec.apps.client.facts import concept_display_name, member_display_name
from edgar_sec.engine.xbrl.normalize.decomposer import split_camel_case
from edgar_sec.engine.xbrl.schema.models import qname_local


def format_cell(val: float | None) -> str:
    """Full-dollar money cell; negatives in parentheses."""
    if val is None:
        return "-"
    if val < 0:
        return f"$({abs(val):,.0f})"
    return f"${val:,.0f}"


def format_pct(pct: float | None) -> str:
    """Signed percent cell."""
    if pct is None:
        return "-"
    return f"{pct * 100:+.1f}%"


def class_display(dimensions: tuple[tuple[str, str], ...]) -> str:
    """Readable class key: axis words paired with member display names."""
    if not dimensions:
        return "None"
    parts = []
    for axis, member in dimensions:
        tokens = list(split_camel_case(qname_local(axis)))
        if tokens and tokens[-1] == "Axis":
            tokens.pop()
        parts.append(f"{' '.join(tokens)}: {member_display_name(member)}")
    return "; ".join(parts)


def choose_scale(values: Iterable[float | None]) -> tuple[float, str | None]:
    """Display scale from the largest absolute value.

    Trillion-scale filings read in billions, million-scale and up in
    millions; anything smaller stays full-dollar with no units note.
    """
    largest = max((abs(v) for v in values if v is not None), default=0.0)
    if largest >= 1e12:
        return 1e9, "billions"
    if largest >= 1e6:
        return 1e6, "millions"
    return 1.0, None


def format_scaled(val: float | None, divisor: float) -> str:
    """Money cell at a display scale; sub-unit magnitudes stay full-dollar."""
    if val is None:
        return "-"
    if divisor == 1.0:
        return format_cell(val)
    scaled = val / divisor
    if scaled != 0 and abs(scaled) < 0.5:
        return format_cell(val)
    if scaled < 0:
        return f"$({abs(scaled):,.0f})"
    return f"${scaled:,.0f}"


def wrap_label(text: str, width: int) -> list[str]:
    """Wrap a label on word boundaries; an over-wide word is hard-split."""
    if width < 1:
        width = 1
    return textwrap.wrap(
        text, width=width, break_long_words=True, break_on_hyphens=False
    ) or [""]


def display_label(label: str, qname: str) -> str:
    """A carried label, humanized when it is the raw local-name fallback."""
    if label == qname_local(qname):
        return concept_display_name(qname)
    return label


def filing_header(
    name: str | None, cik: str | None, accession: str | None
) -> str | None:
    """One-line filing identity from the parts the facade actually knows."""
    parts = []
    if name:
        parts.append(name)
    if cik:
        parts.append(f"CIK {cik}")
    if accession:
        parts.append(f"Accession {accession}")
    return " — ".join(parts) if parts else None
