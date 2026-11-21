from __future__ import annotations

import pytest
import xml.etree.ElementTree as ET

from edgar_sec.engine.forms.common.unparsed import (
    deserialize_unparsed_sections,
    load_unparsed_sections,
    serialize_unparsed_sections,
)


def test_unparsed_sections_use_a_shared_top_level_envelope() -> None:
    records = [
        {
            "role": "table",
            "content_type": "text/html",
            "content": "<table><tr><td>x</td></tr></table>",
        }
    ]

    encoded = serialize_unparsed_sections(records)

    assert deserialize_unparsed_sections(encoded) == tuple(records)


def test_unparsed_sections_reject_invalid_records() -> None:
    with pytest.raises(ValueError, match="record is invalid"):
        serialize_unparsed_sections([{"role": "table", "content": "x"}])


def test_unparsed_sections_reject_invalid_envelopes() -> None:
    with pytest.raises(ValueError, match="envelope"):
        deserialize_unparsed_sections('{"items":[]}')


def test_unparsed_loader_prefers_sibling_sidecar(tmp_path) -> None:
    operations = tmp_path / "operations"
    operations.mkdir()
    records = (
        {
            "role": "table",
            "content_type": "text/html",
            "content": "<table>x</table>",
        },
    )
    (operations / "unparsed_sections.json").write_bytes(
        serialize_unparsed_sections(records)
    )

    assert load_unparsed_sections(tmp_path) == records


def test_unparsed_loader_reads_existing_xml_nodes(tmp_path) -> None:
    root = ET.fromstring(
        '<root><unparsedSection role="table" tableIndex="2">&lt;table&gt;x</unparsedSection></root>'
    )

    records = load_unparsed_sections(tmp_path, root)

    assert records == (
        {
            "role": "table",
            "content_type": "text/html",
            "content": "<table>x",
            "table_index": 2,
        },
    )
