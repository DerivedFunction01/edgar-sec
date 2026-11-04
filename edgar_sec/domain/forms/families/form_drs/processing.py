"""DRS wrapper processing profile."""

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_drs.reports import DrsReport

PROFILE_DRS = DocumentProcessingProfile(
    family="DRS",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    ),
    report_class=DrsReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    review_analyzer="edgar_sec.engine.forms.form_drs.analysis",
    has_toc=True,
    has_sections=False,
    has_notes=False,
    has_xbrl=False,
)

__all__ = ["PROFILE_DRS"]
