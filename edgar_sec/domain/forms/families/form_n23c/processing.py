"""Form N-23C notice family processing profiles."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_n23c.reports import (
    FormN23C1Report,
    FormN23C2Report,
    FormN23C3Report,
)

_OPERATIONS = frozenset(
    {
        AcquisitionOperation.RAW,
        AcquisitionOperation.RENDER_TO_TXT,
    }
)

PROFILE_FORM_N23C1 = DocumentProcessingProfile(
    family="N-23C-1",
    version="v1",
    allowed_operations=_OPERATIONS,
    report_class=FormN23C1Report,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    has_sections=True,
    section_run_in_titles=True,
)

PROFILE_FORM_N23C2 = DocumentProcessingProfile(
    family="N-23C-2",
    version="v1",
    allowed_operations=_OPERATIONS,
    report_class=FormN23C2Report,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    has_sections=True,
    section_run_in_titles=True,
)

PROFILE_FORM_N23C3 = DocumentProcessingProfile(
    family="N-23C-3",
    version="v1",
    allowed_operations=_OPERATIONS,
    report_class=FormN23C3Report,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    has_sections=True,
    section_run_in_titles=True,
)

__all__ = [
    "PROFILE_FORM_N23C1",
    "PROFILE_FORM_N23C2",
    "PROFILE_FORM_N23C3",
]
