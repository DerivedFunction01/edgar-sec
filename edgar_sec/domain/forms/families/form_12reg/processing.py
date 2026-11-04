"""Processing profiles for the Section 12 registration cluster."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_12reg.reports import Form12RegReport

_ANALYZER = "edgar_sec.engine.forms.form_12reg.analysis"
_OPERATIONS = frozenset({AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_TXT})

PROFILE_FORM_25 = DocumentProcessingProfile(
    family="25",
    version="v1",
    allowed_operations=_OPERATIONS,
    report_class=Form12RegReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    review_analyzer=_ANALYZER,
    has_toc=False,
    has_sections=False,
    has_notes=False,
    has_xbrl=False,
)

PROFILE_FORM_8A = DocumentProcessingProfile(
    family="8-A",
    version="v1",
    allowed_operations=_OPERATIONS,
    report_class=Form12RegReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    review_analyzer=_ANALYZER,
    has_toc=True,
    has_sections=True,
    has_notes=False,
    has_xbrl=False,
)

PROFILE_FORM_8B = DocumentProcessingProfile(
    family="8-B",
    version="v1",
    allowed_operations=_OPERATIONS,
    report_class=Form12RegReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    review_analyzer=_ANALYZER,
    has_toc=True,
    has_sections=True,
    has_notes=False,
    has_xbrl=False,
)

__all__ = ["PROFILE_FORM_25", "PROFILE_FORM_8A", "PROFILE_FORM_8B"]
