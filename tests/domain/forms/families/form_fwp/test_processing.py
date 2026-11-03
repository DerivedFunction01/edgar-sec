from __future__ import annotations

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_fwp.processing import PROFILE_FORM_FWP
from edgar_sec.domain.forms.families.form_fwp.reports import FormFWPReport


def test_form_fwp_profile_properties() -> None:
    assert PROFILE_FORM_FWP.family == "FWP"
    assert PROFILE_FORM_FWP.version == "v1"
    assert PROFILE_FORM_FWP.allowed_operations == frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    )
    assert PROFILE_FORM_FWP.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_FORM_FWP.report_class is FormFWPReport
    assert (
        PROFILE_FORM_FWP.review_analyzer == "edgar_sec.engine.forms.form_fwp.analysis"
    )


def test_form_fwp_profile_flags() -> None:
    assert PROFILE_FORM_FWP.has_toc is False
    assert PROFILE_FORM_FWP.has_sections is True
    assert PROFILE_FORM_FWP.has_notes is False
    assert PROFILE_FORM_FWP.has_xbrl is False


def test_form_fwp_profile_operations() -> None:
    assert PROFILE_FORM_FWP.has_operation(AcquisitionOperation.RAW)
    assert PROFILE_FORM_FWP.has_operation(AcquisitionOperation.RENDER_TO_TXT)
    assert not PROFILE_FORM_FWP.has_operation(AcquisitionOperation.RENDER_TO_XML)
