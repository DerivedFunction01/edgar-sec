"""Tests for the S3 parser contract scaffold.

The parser body is intentionally absent; these tests verify the typed interface,
the fail-closed placeholder, and the absence of an HTML/network dependency.
"""

import importlib.util
from typing import Literal

import pytest

from edgar_sec.pipelines.document_inventory.index_parser import (
    IndexPageInput,
    IndexParseFailure,
    IndexParseOutcome,
    ParserDiagnostic,
    ParserDiagnostics,
    ParsedIndexPage,
    UnrecognizedIndexPage,
    parse_html_index,
)


@pytest.mark.parametrize(
    "name",
    [
        "IndexPageInput",
        "ParserDiagnostic",
        "ParserDiagnostics",
        "ParsedIndexPage",
        "UnrecognizedIndexPage",
        "IndexParseFailure",
        "IndexParseOutcome",
        "parse_html_index",
    ],
)
def test_all_public_names_are_importable(name: str) -> None:
    import edgar_sec.pipelines.document_inventory.index_parser as mod

    assert hasattr(mod, name), f"{name} is not exported"


def test_parse_html_index_fails_closed() -> None:
    input_ = IndexPageInput(
        accession="0000123456-12-000001",
        source_url="https://www.sec.gov/Archives/edgar/data/12345/000012345612000001-index.htm",
        response_bytes=b"mock",
    )
    with pytest.raises(NotImplementedError):
        parse_html_index(input_)


def test_parse_html_index_diagnostic_codes_are_complete() -> None:
    import typing

    hints = typing.get_type_hints(ParserDiagnostic)
    codes = typing.get_args(hints["code"])
    expected = {
        "unknown_table",
        "missing_column",
        "missing_sequence",
        "invalid_sequence",
        "duplicate_sequence",
        "out_of_order_sequence",
        "duplicate_filename",
        "invalid_size",
        "unsafe_href",
        "malformed_html",
        "unsupported_encoding",
    }
    assert set(codes) == expected


def test_index_parse_outcome_contains_expected_branches() -> None:
    import typing

    branches = typing.get_args(IndexParseOutcome)
    assert ParsedIndexPage in branches
    assert UnrecognizedIndexPage in branches
    assert IndexParseFailure in branches


def test_parse_html_index_has_no_html_or_network_dependency() -> None:
    """The scaffold must not pull in an HTML parser or HTTP client."""
    import edgar_sec.pipelines.document_inventory.index_parser as mod

    source = mod.__loader__.get_source(mod.__name__)
    assert source is not None
    bad = {"bs4", "lxml", "html5lib", "requests", "httpx", "aiohttp"}
    found = {b for b in bad if f"import {b}" in source or f"from {b}" in source}
    assert not found, f"forbidden dependency found: {found}"


def test_layer_boundary_only_allows_allowed_imports() -> None:
    """index_parser (Layer 4) may only import foundation, infra, domain, and siblings."""
    import ast

    import edgar_sec.pipelines.document_inventory.index_parser as mod

    with open(mod.__file__, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    allowed = {
        "edgar_sec.domain",
        "edgar_sec.infra",
        "edgar_sec.foundation",
        "edgar_sec.pipelines",
    }
    package = ".".join(mod.__name__.split(".")[:-1])
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                top = f"{package}.{node.module or ''}"
            else:
                top = node.module or ""
            if top.startswith("edgar_sec."):
                imports.add(top)
    for imp in imports:
        assert any(imp == a or imp.startswith(a + ".") for a in allowed), (
            f"disallowed import: {imp}"
        )
