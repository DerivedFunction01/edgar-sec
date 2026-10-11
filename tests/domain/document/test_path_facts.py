"""Tests for document path facts classifier."""

from __future__ import annotations

from edgar_sec.domain.document.path_facts import (
    DocumentPathFacts,
    DocumentPathShape,
    DocumentSuffixClass,
    PLACEHOLDER_PRIMARY_FILENAMES,
    archive_root_candidate,
)


class TestDocumentPathFacts:
    """Tests for DocumentPathFacts."""

    def test_archive_path_flat_html(self) -> None:
        """Test flat HTML path classification."""
        facts = DocumentPathFacts.from_archive_path("document.html")
        assert facts.path_shape == DocumentPathShape.FLAT
        assert facts.suffix == ".html"
        assert facts.suffix_class == DocumentSuffixClass.MARKUP

    def test_archive_path_nested_xml(self) -> None:
        """Test nested XML path (XSL rendering) classification."""
        facts = DocumentPathFacts.from_archive_path("xslForm10X/01/document.xml")
        assert facts.path_shape == DocumentPathShape.NESTED
        assert facts.suffix == ".xml"
        assert facts.suffix_class == DocumentSuffixClass.XML

    def test_archive_path_flat_pdf(self) -> None:
        """Test flat PDF path classification."""
        facts = DocumentPathFacts.from_archive_path("exhibit.pdf")
        assert facts.path_shape == DocumentPathShape.FLAT
        assert facts.suffix == ".pdf"
        assert facts.suffix_class == DocumentSuffixClass.PDF

    def test_archive_path_opaque(self) -> None:
        """Test opaque suffix classification."""
        facts = DocumentPathFacts.from_archive_path("document.zip")
        assert facts.suffix_class == DocumentSuffixClass.OPAQUE

    def test_sgml_filename_classification(self) -> None:
        """Test SGML filename classification (flat by definition)."""
        facts = DocumentPathFacts.from_sgml_filename("DOC001.XML")
        assert facts.path_shape == DocumentPathShape.FLAT
        assert facts.suffix == ".xml"
        assert facts.suffix_class == DocumentSuffixClass.XML

    def test_empty_path(self) -> None:
        """Test empty path handling."""
        facts = DocumentPathFacts.from_archive_path("")
        assert facts.path_shape == DocumentPathShape.FLAT
        assert facts.suffix == ""
        assert facts.suffix_class == DocumentSuffixClass.UNKNOWN


class TestArchiveRootCandidate:
    """Tests for archive_root_candidate."""

    def test_nested_path_returns_basename(self) -> None:
        """Test that nested path returns basename."""
        assert archive_root_candidate("xslForm10X/01/document.xml") == "document.xml"

    def test_flat_path_returns_none(self) -> None:
        """Test that flat path returns None."""
        assert archive_root_candidate("document.xml") is None

    def test_empty_path_returns_none(self) -> None:
        """Test that empty path returns None."""
        assert archive_root_candidate("") is None

    def test_none_path_returns_none(self) -> None:
        """Test that None returns None."""
        assert archive_root_candidate(None) is None


def test_placeholder_primary_filename_vocabulary_is_exact() -> None:
    assert PLACEHOLDER_PRIMARY_FILENAMES == {
        "0001.htm",
        "0001.txt",
        "0000.htm",
        "0000.txt",
    }
