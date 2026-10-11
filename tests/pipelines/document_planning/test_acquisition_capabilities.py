"""Tests for S6 acquisition capability catalog."""

from __future__ import annotations

from edgar_sec.pipelines.document_planning.acquisition_capabilities import (
    CATALOG_VERSION,
    CapabilityStatus,
    OutputKind,
    SourceStrategy,
    get_capability,
    get_output_kind,
    get_source_strategy,
    is_operation_supported,
)


class TestCapabilityCatalog:
    """Tests for the capability catalog."""

    def test_catalog_version(self) -> None:
        """Test catalog version is defined."""
        assert CATALOG_VERSION == "v1"

    def test_flat_xml_raw_supported(self) -> None:
        """Test flat XML raw operation is supported."""
        assert is_operation_supported("10-K", "primary", "flat", "xml", "raw")

    def test_flat_xml_render_to_txt_unsupported(self) -> None:
        """Test flat XML render_to_txt is unsupported."""
        assert not is_operation_supported(
            "10-K", "primary", "flat", "xml", "render_to_txt"
        )

    def test_flat_xml_render_to_xml_unsupported(self) -> None:
        """Test flat XML render_to_xml is unsupported."""
        assert not is_operation_supported(
            "10-K", "primary", "flat", "xml", "render_to_xml"
        )

    def test_nested_xml_raw_supported(self) -> None:
        """Test nested XML raw operation is supported."""
        assert is_operation_supported("10-K", "primary", "nested", "xml", "raw")

    def test_nested_xml_render_to_txt_supported(self) -> None:
        """Test nested XML render_to_txt is supported."""
        assert is_operation_supported(
            "10-K", "primary", "nested", "xml", "render_to_txt"
        )

    def test_nested_xml_render_to_xml_supported(self) -> None:
        """Test nested XML render_to_xml is supported."""
        assert is_operation_supported(
            "10-K", "primary", "nested", "xml", "render_to_xml"
        )

    def test_html_markup_raw_supported(self) -> None:
        """Test HTML markup raw is supported."""
        assert is_operation_supported("10-K", "primary", "flat", "markup", "raw")

    def test_html_markup_render_to_txt_supported(self) -> None:
        """Test HTML markup render_to_txt is supported."""
        assert is_operation_supported(
            "10-K", "primary", "flat", "markup", "render_to_txt"
        )

    def test_html_markup_render_to_xml_unsupported(self) -> None:
        """Test HTML markup render_to_xml is unsupported (unless translator registered)."""
        assert not is_operation_supported(
            "10-K", "primary", "flat", "markup", "render_to_xml"
        )

    def test_get_source_strategy_nested_xml(self) -> None:
        """Test source strategy for nested XML render_to_xml."""
        strategy = get_source_strategy(
            "10-K", "primary", "nested", "xml", "render_to_xml"
        )
        assert strategy == SourceStrategy.ARCHIVE_ROOT_XML

    def test_get_output_kind_render_to_txt(self) -> None:
        """Test output kind for render_to_txt."""
        output = get_output_kind("10-K", "primary", "flat", "markup", "render_to_txt")
        assert output == OutputKind.TEXT

    def test_get_output_kind_raw(self) -> None:
        """Test output kind for raw."""
        output = get_output_kind("10-K", "primary", "flat", "xml", "raw")
        assert output == OutputKind.RAW_BYTES

    def test_unknown_operation_unsupported(self) -> None:
        """Test unknown operation is unsupported."""
        assert not is_operation_supported(
            "10-K", "primary", "flat", "xml", "unknown_op"
        )

    def test_opaque_suffix_raw_only(self) -> None:
        """Test opaque suffixes only support raw."""
        assert is_operation_supported("10-K", "primary", "flat", "opaque", "raw")
        assert not is_operation_supported(
            "10-K", "primary", "flat", "opaque", "render_to_txt"
        )

    def test_text_render_to_txt(self) -> None:
        """Test text files support render_to_txt."""
        assert is_operation_supported(
            "10-K", "primary", "flat", "text", "render_to_txt"
        )
