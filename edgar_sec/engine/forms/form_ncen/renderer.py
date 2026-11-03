"""Canonical XML renderer for SEC Form N-CEN filings."""

from __future__ import annotations

from typing import TYPE_CHECKING
import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.form_ncen.models import FormNCenDocument
from edgar_sec.domain.forms.families.form_ncen.taxonomy import (
    N_CEN_NAMESPACE,
    N_CEN_XML_SPEC,
)
from edgar_sec.engine.document_processing.outputs import HandlerOutput
from edgar_sec.engine.forms.common.native_xml import passthrough_sec_xml
from edgar_sec.engine.forms.common.xml_builder import (
    add_text_element,
    canonical_xml_output,
    child_element,
    root_element,
)
from edgar_sec.engine.forms.form_ncen.xml_parser import parse_ncen_xml

if TYPE_CHECKING:
    from edgar_sec.engine.document_processing.registry import HandlerContext

_COMMON_NS = "http://www.sec.gov/edgar/common"


def _q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def build_ncen_xml(doc: FormNCenDocument) -> HandlerOutput:
    """Serialize a FormNCenDocument into the canonical XML envelope."""
    ET.register_namespace("", N_CEN_NAMESPACE)
    ET.register_namespace("com", _COMMON_NS)
    ns = N_CEN_NAMESPACE
    root = root_element(_q(ns, "edgarSubmission"))
    header = child_element(root, _q(ns, "headerData"))
    add_text_element(header, _q(ns, "submissionType"), doc.submission_type)
    filer_info = child_element(header, _q(ns, "filerInfo"))
    if doc.filer_cik is not None:
        filer = child_element(filer_info, _q(ns, "filer"))
        credentials = child_element(filer, _q(ns, "issuerCredentials"))
        add_text_element(credentials, _q(ns, "cik"), doc.filer_cik)
    if doc.period_of_report is not None:
        add_text_element(filer_info, _q(ns, "periodOfReport"), doc.period_of_report)
    form_data = child_element(root, _q(ns, "formData"))
    child_element(form_data, _q(ns, "generalInfo"))
    registrant = child_element(form_data, _q(ns, "registrantInfo"))
    add_text_element(registrant, _q(ns, "registrantFullName"), doc.registrant_name)
    if doc.file_number is not None:
        add_text_element(registrant, _q(ns, "investmentCompFileNo"), doc.file_number)
    if doc.registrant_cik is not None:
        add_text_element(registrant, _q(ns, "registrantCik"), doc.registrant_cik)
    if doc.registrant_lei is not None:
        add_text_element(registrant, _q(ns, "registrantLei"), doc.registrant_lei)
    if doc.city is not None:
        add_text_element(registrant, _q(ns, "registrantcity"), doc.city)
    if doc.state is not None:
        add_text_element(registrant, _q(ns, "registrantstate"), doc.state)
    if doc.country is not None:
        add_text_element(registrant, _q(ns, "registrantcountry"), doc.country)
    if doc.is_first_filing is not None:
        add_text_element(
            registrant, _q(ns, "isRegistrantFirstFiling"), doc.is_first_filing
        )
    if doc.is_last_filing is not None:
        add_text_element(
            registrant, _q(ns, "isRegistrantLastFiling"), doc.is_last_filing
        )
    if doc.classification_type is not None:
        add_text_element(
            registrant,
            _q(ns, "registrantClassificationType"),
            doc.classification_type,
        )
    if doc.directors:
        directors = child_element(registrant, _q(ns, "directors"))
        for name in doc.directors:
            director = child_element(directors, _q(ns, "director"))
            add_text_element(director, _q(ns, "directorName"), name)
    return canonical_xml_output(root)


def render_ncen_to_xml(
    raw_bytes: bytes,
    context: HandlerContext | None = None,
) -> HandlerOutput:
    """Render Form N-CEN raw input to canonical XML with pass-through."""
    passthrough = passthrough_sec_xml(raw_bytes, N_CEN_XML_SPEC)
    if passthrough is not None:
        return passthrough
    doc = parse_ncen_xml(raw_bytes)
    return build_ncen_xml(doc)


__all__ = ["build_ncen_xml", "render_ncen_to_xml"]
