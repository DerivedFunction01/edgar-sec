from __future__ import annotations

from edgar_sec.foundation.checks.git_diff import (
    parse_porcelain_output,
)


def test_parse_empty():
    snap = parse_porcelain_output("")
    assert not snap.has_changes
    assert not snap.is_docs_or_assets_only
    assert snap.python_sources == ()
    assert snap.python_tests == ()


def test_parse_docs_only():
    raw = """ M README.md
?? roadmap/refactor_v2/01_plan.md
 M docs/architecture.rst
"""
    snap = parse_porcelain_output(raw)
    assert snap.has_changes
    assert snap.is_docs_or_assets_only
    assert not snap.touches_root_config
    assert snap.python_sources == ()


def test_parse_python_sources_and_tests():
    raw = """ M edgar_sec/domain/forms/common/aliases.py
 M tests/domain/forms/common/test_aliases.py
?? edgar_sec/engine/document/page_markers/models.py
 D edgar_sec/engine/document/old.py
"""
    snap = parse_porcelain_output(raw)
    assert snap.has_changes
    assert not snap.is_docs_or_assets_only
    assert "edgar_sec/domain/forms/common/aliases.py" in snap.python_sources
    assert "edgar_sec/engine/document/page_markers/models.py" in snap.python_sources
    assert "tests/domain/forms/common/test_aliases.py" in snap.python_tests
    assert "edgar_sec/engine/document/old.py" in snap.deleted_files


def test_parse_root_config():
    raw = """ M tests/conftest.py
"""
    snap = parse_porcelain_output(raw)
    assert snap.touches_root_config
    assert not snap.is_docs_or_assets_only


def test_parse_renames():
    raw = """R  edgar_sec/engine/document/unpacker.py -> edgar_sec/engine/document/unpacking/unpacker.py
"""
    snap = parse_porcelain_output(raw)
    assert "edgar_sec/engine/document/unpacking/unpacker.py" in snap.python_sources
