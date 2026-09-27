"""Public exports for sec_documents package."""

from .models import DocumentRepresentation, PreprocessedDocument
from .preprocessor import (
    DocumentPreprocessor,
    strip_envelope_text,
    strip_sgml_document_wrapper,
)
from .sgml import (
    SgmlSubDocument,
    extract_sub_document,
    find_sub_document,
    resolve_target_sub_document,
    unpack_sgml_submission,
)

__all__ = [
    "DocumentPreprocessor",
    "DocumentRepresentation",
    "PreprocessedDocument",
    "SgmlSubDocument",
    "extract_sub_document",
    "find_sub_document",
    "resolve_target_sub_document",
    "strip_envelope_text",
    "strip_sgml_document_wrapper",
    "unpack_sgml_submission",
]
