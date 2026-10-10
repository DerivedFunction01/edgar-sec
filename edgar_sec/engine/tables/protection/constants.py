"""Sentinel constants for tagged-table protection in plain-text documents."""

from __future__ import annotations

# Byte sequences used to mask <TABLE>...</TABLE> spans during text processing.
# Internal regex patterns and sentinel-logic import these; consumers import directly
# from this module rather than importing from tags.py.
SENTINEL_PREFIX = "__SEC_TBL_"
SENTINEL_SUFFIX = "__"
