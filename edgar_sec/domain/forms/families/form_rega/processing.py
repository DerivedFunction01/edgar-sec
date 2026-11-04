"""Reg A family processing profiles: three XML kinds, two text kinds."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_rega.reports import RegAReport

_ANALYZER = "edgar_sec.engine.forms.form_rega.analysis"
_XML_OPERATIONS = frozenset(
    {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_XML}
)
_TEXT_OPERATIONS = frozenset(
    {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_TXT}
)

PROFILE_REGA_OFFERING = DocumentProcessingProfile(
    family="1-A",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_XML,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    ),
    report_class=RegAReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_XML,
    review_analyzer=_ANALYZER,
)

PROFILE_REGA_ANNUAL = DocumentProcessingProfile(
    family="1-K",
    version="v1",
    allowed_operations=_XML_OPERATIONS,
    report_class=RegAReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_XML,
    review_analyzer=_ANALYZER,
)

PROFILE_REGA_EXIT = DocumentProcessingProfile(
    family="1-Z",
    version="v1",
    allowed_operations=_XML_OPERATIONS,
    report_class=RegAReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_XML,
    review_analyzer=_ANALYZER,
)

PROFILE_REGA_SEMI_ANNUAL = DocumentProcessingProfile(
    family="1-SA",
    version="v1",
    allowed_operations=_TEXT_OPERATIONS,
    report_class=RegAReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    review_analyzer=_ANALYZER,
    has_sections=True,
)

PROFILE_REGA_CURRENT = DocumentProcessingProfile(
    family="1-U",
    version="v1",
    allowed_operations=_TEXT_OPERATIONS,
    report_class=RegAReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    review_analyzer=_ANALYZER,
    has_sections=True,
)

__all__ = [
    "PROFILE_REGA_ANNUAL",
    "PROFILE_REGA_CURRENT",
    "PROFILE_REGA_EXIT",
    "PROFILE_REGA_OFFERING",
    "PROFILE_REGA_SEMI_ANNUAL",
]
