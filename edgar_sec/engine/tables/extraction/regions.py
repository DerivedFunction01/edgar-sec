"""Document regions as hard context for classification.

A context's region derives per geometry, or a builder stamps one; only
the signature region gates, and the producing path is recorded on the
context (``region_path``), never silent.
"""

from __future__ import annotations

from enum import Enum

from edgar_sec.engine.forms.common.signatures.grid import is_signature_table

from .context import TableContext
from .normalize import normalize_text


class Region(str, Enum):
    """The document region a geometry sits in."""

    BODY = "body"
    COVER = "cover"
    SIGNATURE = "signature"
    EXHIBIT = "exhibit"


class RegionPath(str, Enum):
    """The path that produced a context's region value."""

    STAMPED = "stamped"
    DERIVED = "derived"


def _own_text(context: TableContext) -> str:
    return " ".join(
        cell for row in context.rows for cell in row if cell.strip()
    ).lower()


def _is_exhibit(context: TableContext) -> bool:
    section = context.section
    if section is None or not section.title:
        return False
    title = normalize_text(section.title)
    return title.startswith("exhibit index") or "index to exhibits" in title


def derive_regions(
    contexts: list[TableContext] | tuple[TableContext, ...],
) -> tuple[str, ...]:
    """One region value per context, in filing order.

    The signature zone trails the last sectioned geometry; a geometry
    joins it only when the signature classifier claims its own text.
    """
    sectioned = [
        position
        for position, context in enumerate(contexts)
        if context.section is not None and context.section.item is not None
    ]
    first_sectioned = sectioned[0] if sectioned else None
    last_sectioned = sectioned[-1] if sectioned else None
    regions: list[str] = []
    for position, context in enumerate(contexts):
        if _is_exhibit(context):
            regions.append(Region.EXHIBIT.value)
        elif (
            last_sectioned is not None
            and position > last_sectioned
            and is_signature_table(_own_text(context), position > 0)
        ):
            regions.append(Region.SIGNATURE.value)
        elif first_sectioned is not None and position < first_sectioned:
            regions.append(Region.COVER.value)
        else:
            regions.append(Region.BODY.value)
    return tuple(regions)


def effective_regions(
    contexts: list[TableContext] | tuple[TableContext, ...],
) -> tuple[str, ...]:
    """Stamped regions where a builder set them, derived elsewhere."""
    values, _paths = effective_region_paths(contexts)
    return values


def effective_region_paths(
    contexts: list[TableContext] | tuple[TableContext, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Effective region values with the path that produced each one."""
    derived = derive_regions(contexts)
    values: list[str] = []
    paths: list[str] = []
    for position, context in enumerate(contexts):
        if context.region is not None:
            values.append(context.region)
            paths.append(RegionPath.STAMPED.value)
        else:
            values.append(derived[position])
            paths.append(RegionPath.DERIVED.value)
    return tuple(values), tuple(paths)
