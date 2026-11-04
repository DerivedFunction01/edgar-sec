from __future__ import annotations

from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.form_tender.processing import PROFILE_TENDER
from edgar_sec.domain.forms.families.form_tender.reports import TenderReport


def test_tender_profile_properties() -> None:
    assert PROFILE_TENDER.family == "SC TO"
    assert PROFILE_TENDER.version == "v1"
    assert PROFILE_TENDER.allowed_operations == frozenset(
        {
            AcquisitionOperation.RAW,
            AcquisitionOperation.RENDER_TO_TXT,
        }
    )
    assert PROFILE_TENDER.preferred_operation == AcquisitionOperation.RENDER_TO_TXT
    assert PROFILE_TENDER.report_class is TenderReport
    assert (
        PROFILE_TENDER.review_analyzer == "edgar_sec.engine.forms.form_tender.analysis"
    )


def test_tender_profile_flags() -> None:
    assert PROFILE_TENDER.has_toc is True
    assert PROFILE_TENDER.has_sections is True
    assert PROFILE_TENDER.has_notes is False
    assert PROFILE_TENDER.has_xbrl is False


def test_tender_profile_operations() -> None:
    assert PROFILE_TENDER.has_operation(AcquisitionOperation.RAW)
    assert PROFILE_TENDER.has_operation(AcquisitionOperation.RENDER_TO_TXT)
    assert not PROFILE_TENDER.has_operation(AcquisitionOperation.RENDER_TO_XML)
