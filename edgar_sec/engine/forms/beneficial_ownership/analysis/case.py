"""Case analysis loader and evaluator for beneficial ownership submissions."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from edgar_sec.engine.forms.beneficial_ownership.analysis.xml_audit import analyze_xml
from edgar_sec.engine.forms.beneficial_ownership.field_observations import (
    empty_field_observations,
)
from edgar_sec.engine.forms.beneficial_ownership.vocabulary import FIELD_TAGS
from edgar_sec.engine.forms.common.unparsed import load_unparsed_sections


def analyze_case(case_dir: Path, record: dict[str, Any]) -> dict[str, Any] | None:
    """Analyze single beneficial ownership case artifacts and return scorecard."""
    xml_path = case_dir / "operations" / "render_to_xml.xml"
    if (
        not xml_path.is_file()
        and not (case_dir / "operations" / "render_to_txt.txt").is_file()
    ):
        return None
    accession = str(record.get("accession", case_dir.name))
    expected_family = str(record.get("form", record.get("family", "")))
    if not xml_path.is_file():
        return {
            "accession": accession,
            "form": "13G" if "13G" in expected_family.upper() else "13D",
            "family": "13G" if "13G" in expected_family.upper() else "13D",
            "error": "missing_rendered_xml",
            "field_observations": empty_field_observations(FIELD_TAGS),
            "anomalies": [
                {
                    "accession": accession,
                    "kind": "missing_rendered_xml",
                    "detail": "text rendering exists but render_to_xml.xml is absent",
                }
            ],
            "review_signals": [],
            "value_frequencies": {},
            "unparsed_sections": [],
            "date_normalization_evidence": [],
            "extraction_coverage": None,
        }
    source_text: str | None = None
    text_path = case_dir / "operations" / "render_to_txt.txt"
    if text_path.is_file():
        try:
            source_text = text_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            source_text = None
    try:
        xml_text = xml_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return {
            "accession": accession,
            "form": "13G" if "13G" in expected_family.upper() else "13D",
            "family": "13G" if "13G" in expected_family.upper() else "13D",
            "error": "unreadable_xml",
            "field_observations": empty_field_observations(FIELD_TAGS),
            "anomalies": [
                {
                    "accession": accession,
                    "kind": "unreadable_xml",
                    "detail": str(error),
                }
            ],
            "review_signals": [],
            "value_frequencies": {},
            "unparsed_sections": [],
            "date_normalization_evidence": [],
            "extraction_coverage": None,
        }
    unparsed_records: tuple[dict[str, object], ...] = ()
    unparsed_error: str | None = None
    try:
        root = ET.fromstring(xml_text)
        unparsed_records = load_unparsed_sections(case_dir, root)
    except ET.ParseError:
        pass
    except ValueError as error:
        unparsed_error = str(error)
    except OSError as error:
        unparsed_error = str(error)
    return analyze_xml(
        xml_text,
        accession,
        expected_family,
        source_text,
        unparsed_records=unparsed_records,
        unparsed_error=unparsed_error,
    )
