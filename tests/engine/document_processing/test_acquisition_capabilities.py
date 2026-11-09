from edgar_sec.domain.document.path_facts import DocumentPathFacts
from edgar_sec.domain.document.route import content_route, document_route
from edgar_sec.engine.document_processing.acquisition_capabilities import (
    CapabilityStatus,
    resolve_acquisition_capability,
)
from edgar_sec.engine.document_processing.capabilities import get_catalog_version


def test_catalog_version_is_stable() -> None:
    assert get_catalog_version() == "v3"


def test_raw_operation_resolves_stable_handler_pins() -> None:
    facts = DocumentPathFacts.from_archive_path("filing.xml")
    entry = resolve_acquisition_capability("10-K", "primary", "raw", facts)
    assert entry.status is CapabilityStatus.SUPPORTED
    assert entry.pins == ("raw.selected_source", "v1", "raw_identity", "1", "raw_bytes")


def test_capability_resolution_uses_family_policy_and_path_facts() -> None:
    facts = DocumentPathFacts.from_archive_path("filing.htm")
    entry = resolve_acquisition_capability("10-K", "primary", "render_to_txt", facts)
    assert entry.status is CapabilityStatus.SUPPORTED
    assert entry.pins == ("text.markup", "v1", "normalize_document", "1", "text")


def test_pdf_primary_resolves_the_text_pdf_capability() -> None:
    facts = DocumentPathFacts.from_archive_path("filing.pdf")
    entry = resolve_acquisition_capability("10-K", "primary", "render_to_txt", facts)
    assert entry.status is CapabilityStatus.SUPPORTED
    assert entry.pins == ("text.pdf", "v1", "normalize_pdf_document", "1", "text")


def test_unmodelled_family_pdf_resolves_generic_render() -> None:
    facts = DocumentPathFacts.from_archive_path("filing.pdf")
    entry = resolve_acquisition_capability("485", "primary", "render_to_txt", facts)
    assert entry.status is CapabilityStatus.SUPPORTED
    assert entry.pins == ("text.pdf", "1", "normalize_pdf_document", "1", "text")


def test_profile_less_variable_kin_match_unmodelled_posture() -> None:
    for form, family in (
        ("N-4", "N-4"),
        ("N-4/A", "N-4"),
        ("N-6", "N-6"),
        ("N-6/A", "N-6"),
    ):
        for path, operation in (
            ("filing.htm", "render_to_txt"),
            ("filing.txt", "render_to_txt"),
            ("filing.pdf", "render_to_txt"),
            ("filing.htm", "raw"),
        ):
            facts = DocumentPathFacts.from_archive_path(path)
            entry = resolve_acquisition_capability(form, "primary", operation, facts)
            baseline = resolve_acquisition_capability(
                "40-17G", "primary", operation, facts
            )
            assert entry.family == family
            assert entry.status is baseline.status
            assert entry.pins == baseline.pins


def test_nsar_fil_primary_resolves_the_plain_text_capability() -> None:
    facts = DocumentPathFacts.from_archive_path("answer.fil")
    entry = resolve_acquisition_capability("NSAR", "primary", "render_to_txt", facts)
    assert entry.status is CapabilityStatus.SUPPORTED
    assert entry.pins == ("text.plain", "v1", "normalize_document", "1", "text")


def test_opaque_suffix_stays_unsupported_for_render_to_txt() -> None:
    facts = DocumentPathFacts.from_archive_path("filing.zip")
    entry = resolve_acquisition_capability("NSAR", "primary", "render_to_txt", facts)
    assert entry.status is CapabilityStatus.UNSUPPORTED
    assert entry.pins is None


def test_image_suffix_on_the_binary_route_stays_unsupported() -> None:
    facts = DocumentPathFacts.from_archive_path("filing.gif")
    entry = resolve_acquisition_capability("10-K", "primary", "render_to_txt", facts)
    assert entry.status is CapabilityStatus.UNSUPPORTED
    assert entry.pins is None


def test_flat_xml_does_not_resolve_text_processing() -> None:
    facts = DocumentPathFacts.from_archive_path("filing.xml")
    entry = resolve_acquisition_capability("10-K", "primary", "render_to_txt", facts)
    assert entry.status is CapabilityStatus.UNSUPPORTED
    assert entry.pins is None


def test_nested_xsl_xml_uses_rendered_markup_capability() -> None:
    facts = DocumentPathFacts.from_archive_path("xsl10K_X01/filing.xml")
    entry = resolve_acquisition_capability(
        "10-K", "primary", "render_to_txt", facts, document_route(facts.path_context)
    )
    assert entry.capability_id == "text.rendered_markup"
    assert entry.status is CapabilityStatus.SUPPORTED


def test_sgml_filename_slashes_use_content_route() -> None:
    filename = "xsl10K_X01/filing.xml"
    facts = DocumentPathFacts.from_sgml_filename(filename)
    entry = resolve_acquisition_capability(
        "10-K", "primary", "render_to_txt", facts, content_route(filename)
    )
    assert facts.path_shape.value == "flat"
    assert entry.status is CapabilityStatus.UNSUPPORTED


def test_unmodelled_family_resolves_generic_render_to_txt() -> None:
    facts = DocumentPathFacts.from_archive_path("filing.htm")
    entry = resolve_acquisition_capability("485", "primary", "render_to_txt", facts)
    assert entry.status is CapabilityStatus.SUPPORTED
    assert entry.pins == ("text.markup", "1", "normalize_document", "1", "text")


def test_unmodelled_family_resolves_plain_text_render() -> None:
    facts = DocumentPathFacts.from_archive_path("filing.txt")
    entry = resolve_acquisition_capability("485", "primary", "render_to_txt", facts)
    assert entry.status is CapabilityStatus.SUPPORTED
    assert entry.pins == ("text.plain", "1", "normalize_document", "1", "text")


def test_unmodelled_family_keeps_raw_and_denies_render_to_xml() -> None:
    facts = DocumentPathFacts.from_archive_path("filing.htm")
    raw = resolve_acquisition_capability("485", "primary", "raw", facts)
    xml = resolve_acquisition_capability("485", "primary", "render_to_xml", facts)
    assert raw.status is CapabilityStatus.SUPPORTED
    assert raw.pins == ("raw.selected_source", "v1", "raw_identity", "1", "raw_bytes")
    assert xml.status is CapabilityStatus.UNSUPPORTED
    assert xml.pins is None


def test_profile_less_tail_family_pdf_resolves_generic_pdf_render() -> None:
    facts = DocumentPathFacts.from_archive_path("filing.pdf")
    entry = resolve_acquisition_capability(
        "NRSRO-CE", "primary", "render_to_txt", facts
    )
    assert entry.status is CapabilityStatus.SUPPORTED
    assert entry.family == "NRSRO-CE"
    assert entry.pins == ("text.pdf", "1", "normalize_pdf_document", "1", "text")


def test_profile_less_tail_member_canonicalizes_to_base_family() -> None:
    facts = DocumentPathFacts.from_archive_path("filing.htm")
    entry = resolve_acquisition_capability("SF-1MEF", "primary", "render_to_txt", facts)
    assert entry.status is CapabilityStatus.SUPPORTED
    assert entry.family == "SF-1"
    assert entry.pins == ("text.markup", "1", "normalize_document", "1", "text")


def test_profile_less_tail_paper_primary_keeps_raw_only_posture() -> None:
    facts = DocumentPathFacts.from_archive_path("filing.paper")
    raw = resolve_acquisition_capability("2-E", "primary", "raw", facts)
    text = resolve_acquisition_capability("2-E", "primary", "render_to_txt", facts)
    assert raw.status is CapabilityStatus.SUPPORTED
    assert raw.pins == ("raw.selected_source", "v1", "raw_identity", "1", "raw_bytes")
    assert text.status is CapabilityStatus.UNSUPPORTED
    assert text.pins is None


def test_profile_less_tail_flat_xml_render_to_txt_is_not_applicable() -> None:
    facts = DocumentPathFacts.from_archive_path("primary_doc.xml")
    entry = resolve_acquisition_capability("2-E", "primary", "render_to_txt", facts)
    assert entry.status is CapabilityStatus.NOT_APPLICABLE
    assert entry.pins is None


def test_unmodelled_family_flat_xml_render_to_txt_is_not_applicable() -> None:
    facts = DocumentPathFacts.from_archive_path("primary_doc.xml")
    entry = resolve_acquisition_capability("F-X", "primary", "render_to_txt", facts)
    assert entry.status is CapabilityStatus.NOT_APPLICABLE
    assert entry.pins is None


def test_unmodelled_family_flat_xml_keeps_raw_supported() -> None:
    facts = DocumentPathFacts.from_archive_path("primary_doc.xml")
    entry = resolve_acquisition_capability("F-X", "primary", "raw", facts)
    assert entry.status is CapabilityStatus.SUPPORTED
    assert entry.pins == ("raw.selected_source", "v1", "raw_identity", "1", "raw_bytes")


def test_unmodelled_family_xsl_xml_keeps_rendered_markup() -> None:
    facts = DocumentPathFacts.from_archive_path("xslF345X03/primary_doc.xml")
    entry = resolve_acquisition_capability(
        "F-X", "primary", "render_to_txt", facts, document_route(facts.path_context)
    )
    assert entry.status is CapabilityStatus.SUPPORTED
    assert entry.capability_id == "text.rendered_markup"


def test_unmodelled_family_xml_exhibit_stays_unsupported() -> None:
    facts = DocumentPathFacts.from_archive_path("primary_doc.xml")
    entry = resolve_acquisition_capability("F-X", "exhibit", "render_to_txt", facts)
    assert entry.status is CapabilityStatus.UNSUPPORTED
    assert entry.pins is None


def test_registered_xml_family_profile_governs_render_to_txt() -> None:
    facts = DocumentPathFacts.from_archive_path("primary_doc.xml")
    entry = resolve_acquisition_capability("N-CR", "primary", "render_to_txt", facts)
    assert entry.status is CapabilityStatus.UNSUPPORTED
    assert entry.pins is None


def test_unknown_operation_is_unsupported() -> None:
    facts = DocumentPathFacts.from_archive_path("filing.xml")
    entry = resolve_acquisition_capability("10-K", "primary", "unknown", facts)
    assert entry.status is CapabilityStatus.UNSUPPORTED


def test_form_4_resolves_render_to_xml() -> None:
    facts = DocumentPathFacts.from_archive_path("nbr59.htm")
    entry = resolve_acquisition_capability("4", "primary", "render_to_xml", facts)
    assert entry.status is CapabilityStatus.SUPPORTED
    assert entry.pins == ("4.render_to_xml", "v1", "form4_html_to_xml", "2", "xml")


def test_form_4_does_not_resolve_render_to_txt() -> None:
    facts = DocumentPathFacts.from_archive_path("nbr59.htm")
    entry = resolve_acquisition_capability("4", "primary", "render_to_txt", facts)
    assert entry.status is CapabilityStatus.UNSUPPORTED
    assert entry.pins is None


def test_form_4_exhibit_uses_generic_text_but_not_form_xml() -> None:
    facts = DocumentPathFacts.from_archive_path("form4-ex99.htm")

    text = resolve_acquisition_capability("4", "exhibit", "render_to_txt", facts)
    xml = resolve_acquisition_capability("4", "exhibit", "render_to_xml", facts)

    assert text.status is CapabilityStatus.SUPPORTED
    assert text.pins == ("text.markup", "v1", "normalize_document", "1", "text")
    assert xml.status is CapabilityStatus.UNSUPPORTED
    assert xml.pins is None


def test_10k_exhibit_keeps_text_capability() -> None:
    facts = DocumentPathFacts.from_archive_path("ex-21.htm")
    entry = resolve_acquisition_capability("10-K", "exhibit", "render_to_txt", facts)
    xml = resolve_acquisition_capability("10-K", "exhibit", "render_to_xml", facts)
    assert entry.status is CapabilityStatus.SUPPORTED
    assert xml.status is CapabilityStatus.UNSUPPORTED
