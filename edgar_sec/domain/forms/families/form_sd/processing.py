"""Processing profile for Form SD."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_sd.reports import FormSDReport

_ANALYZER = "edgar_sec.engine.forms.form_sd.analysis"
_OPERATIONS = frozenset({AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_TXT})

PROFILE_SD = DocumentProcessingProfile(
    family="SD",
    version="v1",
    allowed_operations=_OPERATIONS,
    report_class=FormSDReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    review_analyzer=_ANALYZER,
    has_toc=False,
    has_sections=True,
    has_notes=False,
    has_xbrl=False,
)

__all__ = ["PROFILE_SD"]
