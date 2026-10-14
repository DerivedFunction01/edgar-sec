from edgar_sec.domain.document.path_facts import DocumentPathFacts
from edgar_sec.domain.document.route import content_route, document_route
from edgar_sec.engine.document_processing.acquisition_capabilities import (
    CapabilityStatus,
    resolve_acquisition_capability,
)
from edgar_sec.engine.document_processing.capabilities import get_catalog_version


def test_catalog_version_is_stable() -> None:
    assert get_catalog_version() == "v2"


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


def test_unknown_operation_is_unsupported() -> None:
    facts = DocumentPathFacts.from_archive_path("filing.xml")
    entry = resolve_acquisition_capability("10-K", "primary", "unknown", facts)
    assert entry.status is CapabilityStatus.UNSUPPORTED
