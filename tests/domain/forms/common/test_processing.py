"""Tests for document processing profiles."""

from __future__ import annotations

from edgar_sec.domain.forms.common.processing import (
    DEFAULT_OPERATIONS,
    AcquisitionOperation,
    DocumentProcessingProfile,
    allowed_operations_of,
    profile_version_of,
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

    def test_default_operations_grant_raw_and_generic_text(self) -> None:
        """Unmodelled families default to raw plus generic render-to-text."""
        assert DEFAULT_OPERATIONS == frozenset(
            {AcquisitionOperation.RAW, AcquisitionOperation.RENDER_TO_TXT}
        )

    def test_operations_are_frozen(self) -> None:
        """Test that allowed_operations is immutable."""
        profile = DocumentProcessingProfile(
            family="10-Q",
            version="v1",
            allowed_operations=frozenset({AcquisitionOperation.RAW}),
        )
        assert isinstance(profile.allowed_operations, frozenset)


class TestProfileFallbacks:
    """Tests for the shared profile-or-default resolution helpers."""

    def test_allowed_operations_of_profile(self) -> None:
        """A modelled profile resolves its own allowed operations."""
        profile = DocumentProcessingProfile(
            family="4",
            version="v9",
            allowed_operations=frozenset({AcquisitionOperation.RAW}),
        )
        assert allowed_operations_of(profile) == frozenset({AcquisitionOperation.RAW})

    def test_allowed_operations_of_unmodelled(self) -> None:
        """An unmodelled family resolves the default operations."""
        assert allowed_operations_of(None) == DEFAULT_OPERATIONS
        assert AcquisitionOperation.RENDER_TO_TXT in allowed_operations_of(None)
        assert AcquisitionOperation.RENDER_TO_XML not in allowed_operations_of(None)

    def test_profile_version_of_profile(self) -> None:
        """A modelled profile resolves its own version."""
        profile = DocumentProcessingProfile(
            family="4",
            version="v9",
            allowed_operations=frozenset({AcquisitionOperation.RAW}),
        )
        assert profile_version_of(profile) == "v9"

    def test_profile_version_of_unmodelled(self) -> None:
        """An unmodelled family resolves the default version stamp."""
        assert profile_version_of(None) == "1"
