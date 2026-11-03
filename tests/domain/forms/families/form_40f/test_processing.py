from __future__ import annotations

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_40f.processing import PROFILE_FORM_40F
from edgar_sec.domain.forms.families.form_40f.reports import Form40FReport


def test_form_40f_profile_properties() -> None:
    assert PROFILE_FORM_40F.family == "40-F"
    assert PROFILE_FORM_40F.version == "v1"
    assert PROFILE_FORM_40F.allowed_operations == frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    )
    assert PROFILE_FORM_40F.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_FORM_40F.report_class is Form40FReport
    assert (
        PROFILE_FORM_40F.review_analyzer == "edgar_sec.engine.forms.form_40f.analysis"
    )


def test_form_40f_profile_flags() -> None:
    assert PROFILE_FORM_40F.has_toc is True
    assert PROFILE_FORM_40F.has_sections is True
    assert PROFILE_FORM_40F.has_notes is True
    assert PROFILE_FORM_40F.has_xbrl is True
    assert not PROFILE_FORM_40F.has_operation(AcquisitionOperation.RENDER_TO_XML)
