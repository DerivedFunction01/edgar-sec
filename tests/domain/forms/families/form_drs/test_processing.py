from __future__ import annotations

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_drs.processing import PROFILE_DRS
from edgar_sec.domain.forms.families.form_drs.reports import DrsReport


def test_drs_profile_properties() -> None:
    assert PROFILE_DRS.family == "DRS"
    assert PROFILE_DRS.version == "v1"
    assert PROFILE_DRS.allowed_operations == frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    )
    assert PROFILE_DRS.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_DRS.report_class is DrsReport
    assert PROFILE_DRS.review_analyzer == "edgar_sec.engine.forms.form_drs.analysis"


def test_drs_profile_flags() -> None:
    assert PROFILE_DRS.has_toc is True
    assert PROFILE_DRS.has_sections is False
    assert PROFILE_DRS.has_notes is False
    assert PROFILE_DRS.has_xbrl is False


def test_drs_profile_operations() -> None:
    assert PROFILE_DRS.has_operation(AcquisitionOperation.RAW)
    assert PROFILE_DRS.has_operation(AcquisitionOperation.RENDER_TO_TXT)
    assert not PROFILE_DRS.has_operation(AcquisitionOperation.RENDER_TO_XML)
