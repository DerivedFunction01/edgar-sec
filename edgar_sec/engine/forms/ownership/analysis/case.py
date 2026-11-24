"""Case analysis loader for ownership review submissions."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from edgar_sec.engine.forms.common.xml.unparsed import load_unparsed_sections
from edgar_sec.engine.forms.ownership.analysis.xml_audit import analyze_ownership_xml


def analyze_ownership_review_case(
    case_dir: Path, record: dict[str, Any]
) -> dict[str, Any] | None:
    """Analyze a single review case directory producing ownership diagnostics."""
    accession = str(record.get("accession", ""))
    xml_path = case_dir / "operations" / "render_to_xml.xml"
    if not xml_path.is_file():
        return None
    xml_bytes = xml_path.read_bytes()
    root = ET.fromstring(xml_bytes)
    unparsed_sections = load_unparsed_sections(case_dir, root)
    return analyze_ownership_xml(
        xml_bytes, accession=accession, unparsed_sections=unparsed_sections
    )


analyze_case = analyze_ownership_review_case
