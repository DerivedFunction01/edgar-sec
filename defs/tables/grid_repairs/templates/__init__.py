"""Index and registration of grid repair templates."""

from __future__ import annotations

from ..base import GridTemplate
from .maturity import (
    HEADERLESS_MATURITY_TEMPLATE,
    collapse_headerless_maturity_groups,
    match_headerless_maturity_groups,
)
from .spans import (
    REPEATED_VALUE_GROUP_TEMPLATE,
    YEAR_VALUE_GROUP_TEMPLATE,
    collapse_span_groups,
    match_repeated_value_groups,
    match_year_value_groups,
)

GRID_TEMPLATES: tuple[GridTemplate, ...] = (
    HEADERLESS_MATURITY_TEMPLATE,
    YEAR_VALUE_GROUP_TEMPLATE,
    REPEATED_VALUE_GROUP_TEMPLATE,
)

__all__ = [
    "GRID_TEMPLATES",
    "HEADERLESS_MATURITY_TEMPLATE",
    "REPEATED_VALUE_GROUP_TEMPLATE",
    "YEAR_VALUE_GROUP_TEMPLATE",
    "collapse_headerless_maturity_groups",
    "collapse_span_groups",
    "match_headerless_maturity_groups",
    "match_repeated_value_groups",
    "match_year_value_groups",
]
