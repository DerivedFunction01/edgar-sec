"""Tests for document processing profiles."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)


class TestDocumentProcessingProfile:
    """Tests for DocumentProcessingProfile."""

    def test_default_operations(self) -> None:
        """Test profile with all operations."""
        profile = DocumentProcessingProfile(
            family="10-K",
            version="v1",
            allowed_operations=frozenset(
                {
                    AcquisitionOperation.RAW,
                    AcquisitionOperation.RENDER_TO_TXT,
                    AcquisitionOperation.RENDER_TO_XML,
                }
            ),
        )
        assert profile.family == "10-K"
        assert profile.version == "v1"
        assert profile.has_operation(AcquisitionOperation.RAW)
        assert profile.has_operation(AcquisitionOperation.RENDER_TO_TXT)
        assert profile.has_operation(AcquisitionOperation.RENDER_TO_XML)

    def test_has_operation(self) -> None:
        """Test has_operation method."""
        profile = DocumentProcessingProfile(
            family="8-K",
            version="v1",
            allowed_operations=frozenset(
                {
                    AcquisitionOperation.RAW,
                    AcquisitionOperation.RENDER_TO_TXT,
                }
            ),
        )
        assert profile.has_operation(AcquisitionOperation.RAW)
        assert profile.has_operation(AcquisitionOperation.RENDER_TO_TXT)
        assert not profile.has_operation(AcquisitionOperation.RENDER_TO_XML)

    def test_operations_are_frozen(self) -> None:
        """Test that allowed_operations is immutable."""
        profile = DocumentProcessingProfile(
            family="10-Q",
            version="v1",
            allowed_operations=frozenset({AcquisitionOperation.RAW}),
        )
        assert isinstance(profile.allowed_operations, frozenset)
