"""Shared cover-boundary evidence and conservative detector.

Re-exports the full public API from the boundary submodules so that
existing imports from ``defs.sec_forms.cover.boundary`` continue to work
unchanged after the module was split into this package.
"""

from __future__ import annotations

from defs.sec_forms.cover.body_search import (  # noqa: F401
    _confirm_backward_body,
    _find_body_root_backward,
    _next_nonblank_line,
)
from defs.sec_forms.cover.cover_start import find_cover_start
from defs.sec_forms.cover.models import (
    BodyRoot,
    BoundaryEvidence,
    BoundaryInput,
    BoundaryMethod,
    BoundarySignal,
    CoverBoundary,
    CoverBoundaryPolicy,
    CoverStart,
    DocumentTopology,
    ItemDefinition,
)
from defs.sec_forms.cover.rules import (  # noqa: F401
    CompiledCoverRules,
    compile_cover_rules,
)
from defs.sec_forms.cover.structure import (  # noqa: F401
    RE_ITEM_REFERENCE,
    is_continuation_prose,
    is_preceding_continuation,
    match_structural_line,
)
from defs.sec_forms.cover.toc import (  # noqa: F401
    RE_TOC_HEADING,
    RE_TOC_NUMERIC_LABEL,
    find_toc_span,
    looks_like_toc_row,
    looks_like_toc_tabular,
)
from defs.sec_forms.page_markers import PageMarkerKind, find_page_markers  # noqa: F401

from .body_prose import (  # noqa: F401
    _find_body_prose_line,
    _return_with_heading,
)
from .detection import (
    find_cover_boundary,
    find_cover_boundary_for_profile,
)
from .finalize import _finalize_boundary, _unknown  # noqa: F401
from .helpers import (  # noqa: F401
    _QUOTED_SECTION_MARKERS,
    _RE_TAGGED_TABLE_CLOSE,
    _RE_TAGGED_TABLE_OPEN,
    _REFERENCE_DESCRIPTION_MARKERS,
    _TOC_TRANSITION_ROW_GAP,
    _enabled,
    _is_proxy_reference_disclosure,
    _line_at_offset,
    _line_offset,
    _prev_nonblank_line,
)
from .transition import (  # noqa: F401
    _first_body_semantic_line,
    _next_cover_transition,
)

__all__ = [
    "BodyRoot",
    "BoundaryEvidence",
    "BoundaryInput",
    "BoundaryMethod",
    "BoundarySignal",
    "CoverBoundary",
    "CoverBoundaryPolicy",
    "CoverStart",
    "DocumentTopology",
    "ItemDefinition",
    "_confirm_backward_body",
    "_find_body_root_backward",
    "find_cover_boundary",
    "find_cover_boundary_for_profile",
    "find_cover_start",
    "resolve_document_topology",
]


def __getattr__(name: str):
    if name == "resolve_document_topology":
        from defs.sec_forms.cover.topology import resolve_document_topology as _resolve

        globals()[name] = _resolve
        return _resolve
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
