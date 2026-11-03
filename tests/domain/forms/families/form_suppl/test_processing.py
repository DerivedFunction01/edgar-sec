from __future__ import annotations

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_suppl.processing import PROFILE_FORM_SUPPL
from edgar_sec.domain.forms.families.form_suppl.reports import FormSupplReport


def test_form_suppl_profile_properties() -> None:
    assert PROFILE_FORM_SUPPL.family == "SUPPL"
    assert PROFILE_FORM_SUPPL.version == "v1"
    assert PROFILE_FORM_SUPPL.allowed_operations == frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    )
    assert PROFILE_FORM_SUPPL.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_FORM_SUPPL.report_class is FormSupplReport
    assert (
        PROFILE_FORM_SUPPL.review_analyzer
        == "edgar_sec.engine.forms.form_suppl.analysis"
    )


def test_form_suppl_profile_flags() -> None:
    assert PROFILE_FORM_SUPPL.has_toc is True
    assert PROFILE_FORM_SUPPL.has_sections is True
    assert PROFILE_FORM_SUPPL.has_notes is False
    assert PROFILE_FORM_SUPPL.has_xbrl is False
