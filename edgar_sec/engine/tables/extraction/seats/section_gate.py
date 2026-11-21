"""Section-position gating: the declared section map as genre reach.

Statement-family claims at MD&A or directors position are refused
by position alone, with the refusal recorded; other positions are
silent.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from edgar_sec.engine.tables.extraction.core.normalize import normalize_text
from edgar_sec.engine.tables.extraction.core.registry import (
    PRIMARY_STATEMENT_FAMILIES,
)

STATEMENT_FAMILIES = frozenset(PRIMARY_STATEMENT_FAMILIES)

_MDA_TITLE = "management's discussion and analysis"
_FS_TITLE = "financial statements"

# One declared-map row: (form base, part, item, scope name), carried
# on the classification policy; the forms layer owns the map itself.
ScopeRow = tuple[str, str | None, str, str]


class SectionScope(Enum):
    """Where a section sits relative to the financial statements."""

    FINANCIAL_STATEMENTS = "financial_statements"
    MDA = "mda"
    DIRECTORS = "directors"
    OTHER = "other"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class GenreRefusal:
    """One statement-family claim refused by section position."""

    family: str
    scope: SectionScope
    form: str | None
    part: str | None
    item: str | None
    detail: str


def _base_form(form: str | None) -> str | None:
    if form is None:
        return None
    return form.split("/")[0].strip().upper()


def section_scope(
    scopes: tuple[ScopeRow, ...],
    form: str | None,
    part: str | None,
    item: str | None,
    title: str | None = None,
) -> SectionScope:
    """The declared scope of one section position.

    A title naming MD&A or the financial statements decides ahead
    of the injected item map; unmapped positions stay silent.
    """
    if title:
        normalized = normalize_text(title)
        if _MDA_TITLE in normalized:
            return SectionScope.MDA
        if _FS_TITLE in normalized:
            return SectionScope.FINANCIAL_STATEMENTS
    if item is None:
        return SectionScope.UNKNOWN
    item_key = item.strip().upper()
    part_key = part.strip().upper() if part else None
    base = _base_form(form)
    for form_base, map_part, map_item, scope_name in scopes:
        if map_item != item_key:
            continue
        if map_part is not None and map_part != part_key:
            continue
        if base is not None and base != form_base:
            continue
        if base is None and map_part is not None:
            continue
        return SectionScope(scope_name)
    return SectionScope.OTHER


_REFUSING_SCOPES = {
    SectionScope.MDA: "MD&A",
    SectionScope.DIRECTORS: "a directors section",
}


def genre_refusal(
    scopes: tuple[ScopeRow, ...],
    family: str,
    form: str | None,
    part: str | None,
    item: str | None,
    title: str | None = None,
) -> GenreRefusal | None:
    """Refuse a statement-family claim at a refusing position.

    Only statement families refuse, and only at MD&A or a directors section.
    """
    if family not in STATEMENT_FAMILIES:
        return None
    scope = section_scope(scopes, form, part, item, title)
    if scope not in _REFUSING_SCOPES:
        return None
    where = " ".join(part for part in (form, part, item) if part)
    return GenreRefusal(
        family=family,
        scope=scope,
        form=form,
        part=part,
        item=item,
        detail=(
            f"{family} refused by section position: "
            f"{where} is {_REFUSING_SCOPES[scope]}"
        ),
    )
