"""ABS-EE companion processing profile (exhibits only, no form family)."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_abs_ee.reports import AbsEeReport

PROFILE_ABS_EE = DocumentProcessingProfile(
    family="ABS-EE",
    version="v1",
    allowed_operations=frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_XML,
        }
    ),
    report_class=AbsEeReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_XML,
    review_analyzer="edgar_sec.engine.forms.form_abs_ee.analysis",
)

__all__ = ["PROFILE_ABS_EE"]
