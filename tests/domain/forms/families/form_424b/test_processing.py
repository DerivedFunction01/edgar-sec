from __future__ import annotations

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_424b.processing import PROFILE_FORM_424B
from edgar_sec.domain.forms.families.form_424b.reports import Form424BReport


def test_form_424b_profile_properties() -> None:
    assert PROFILE_FORM_424B.family == "424B"
    assert PROFILE_FORM_424B.version == "v1"
    assert PROFILE_FORM_424B.allowed_operations == frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    )
    assert PROFILE_FORM_424B.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_FORM_424B.report_class is Form424BReport
    assert (
        PROFILE_FORM_424B.review_analyzer == "edgar_sec.engine.forms.form_424b.analysis"
    )


def test_form_424b_profile_flags() -> None:
    assert PROFILE_FORM_424B.has_toc is True
    assert PROFILE_FORM_424B.has_sections is True
    assert PROFILE_FORM_424B.has_notes is True
    assert PROFILE_FORM_424B.has_xbrl is True


def test_form_424b_profile_operations() -> None:
    assert PROFILE_FORM_424B.has_operation(AcquisitionOperation.RAW)
    assert PROFILE_FORM_424B.has_operation(AcquisitionOperation.RENDER_TO_TXT)
    assert not PROFILE_FORM_424B.has_operation(AcquisitionOperation.RENDER_TO_XML)
