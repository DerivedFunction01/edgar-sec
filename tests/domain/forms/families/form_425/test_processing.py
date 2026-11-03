from __future__ import annotations

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_425.processing import PROFILE_FORM_425
from edgar_sec.domain.forms.families.form_425.reports import Form425Report


def test_form_425_profile_properties() -> None:
    assert PROFILE_FORM_425.family == "425"
    assert PROFILE_FORM_425.version == "v1"
    assert PROFILE_FORM_425.allowed_operations == frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    )
    assert PROFILE_FORM_425.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_FORM_425.report_class is Form425Report
    assert PROFILE_FORM_425.review_analyzer == "edgar_sec.engine.forms.form_425.analysis"


def test_form_425_profile_flags() -> None:
    assert PROFILE_FORM_425.has_toc is False
    assert PROFILE_FORM_425.has_sections is False
    assert PROFILE_FORM_425.has_notes is False
    assert PROFILE_FORM_425.has_xbrl is False


def test_form_425_profile_operations() -> None:
    assert PROFILE_FORM_425.has_operation(AcquisitionOperation.RAW)
    assert PROFILE_FORM_425.has_operation(AcquisitionOperation.RENDER_TO_TXT)
    assert not PROFILE_FORM_425.has_operation(AcquisitionOperation.RENDER_TO_XML)
