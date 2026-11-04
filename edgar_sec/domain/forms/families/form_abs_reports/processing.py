"""Processing profile for the ABS text reports (10-D / ABS-15G).

Both faces register under the canonical ``ABS`` family — the Step 3
alias map merges the two codes there — so one profile carries both;
the analyzer dispatches fields by the filing's own form code.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.families.form_abs_reports.reports import (
    FormAbsReportsReport,
)

PROFILE_ABS_REPORTS = DocumentProcessingProfile(
    family="ABS",
    version="v1",
    allowed_operations=frozenset(
        {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_TXT}
    ),
    report_class=FormAbsReportsReport,
    preferred_operation=AcquisitionOperation.RENDER_TO_TXT,
    review_analyzer="edgar_sec.engine.forms.form_abs_reports.analysis",
    has_toc=False,
    has_sections=True,
    has_notes=False,
    has_xbrl=False,
)

__all__ = ["PROFILE_ABS_REPORTS"]
