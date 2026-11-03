"""MJDS family processing profiles on one shared cover posture."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_mjds.reports import FormMjdsReport

_ANALYZER = "edgar_sec.engine.forms.form_mjds.analysis"


def _profile(family: str) -> DocumentProcessingProfile:
    return DocumentProcessingProfile(
        family=family,
        version="v1",
        allowed_operations=frozenset(
            {
                AcquisitionOperation.RAW,
                AcquisitionOperation.RENDER_TO_TXT,
            }
        ),
        report_class=FormMjdsReport,
        preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
        review_analyzer=_ANALYZER,
        has_toc=True,
        has_sections=True,
        has_notes=True,
        has_xbrl=True,
    )


PROFILE_FORM_F7 = _profile("F-7")
PROFILE_FORM_F8 = _profile("F-8")
PROFILE_FORM_F9 = _profile("F-9")
PROFILE_FORM_F10 = _profile("F-10")
PROFILE_FORM_F80 = _profile("F-80")

__all__ = [
    "PROFILE_FORM_F10",
    "PROFILE_FORM_F7",
    "PROFILE_FORM_F80",
    "PROFILE_FORM_F8",
    "PROFILE_FORM_F9",
]
