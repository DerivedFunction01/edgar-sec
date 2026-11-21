"""Vocabulary for ABS asset-data exhibits (ABS XML spec v3.1)."""

from __future__ import annotations

# EX-102 documents live in a per-asset-class namespace under this prefix;
# the class segment is open-ended and recorded verbatim.
ASSETDATA_NAMESPACE_PREFIX = "http://www.sec.gov/edgar/document/absee/"
ASSETDATA_NAMESPACE_SUFFIX = "/assetdata"

ASSETDATA_ROOT_TAG = "assetdata"
ASSET_RECORD_TAG = "assets"

# The CMBS flavor of EX-103 carries narrative as structured entries
# under a namespace-less <comments> root instead of XML comments.
COMMENTS_ROOT_TAG = "comments"
COMMENT_RECORD_TAG = "commentData"

EXHIBIT_TYPES = ("EX-102", "EX-103")

# Host submission forms whose exhibits the companion scope covers.
HOST_FORMS = ("ABS-EE", "10-D")

# Classes with published schemas in the ABS XML specification.
SPEC_ASSET_CLASSES = frozenset(
    {"autolease", "autoloan", "cmbs", "debtsecurities", "rmbs"}
)

__all__ = [
    "ASSETDATA_NAMESPACE_PREFIX",
    "ASSETDATA_NAMESPACE_SUFFIX",
    "ASSETDATA_ROOT_TAG",
    "ASSET_RECORD_TAG",
    "COMMENTS_ROOT_TAG",
    "COMMENT_RECORD_TAG",
    "EXHIBIT_TYPES",
    "HOST_FORMS",
    "SPEC_ASSET_CLASSES",
]
