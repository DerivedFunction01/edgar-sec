from __future__ import annotations

import xml.etree.ElementTree as ET

from edgar_sec.engine.forms.common.extraction import (
    deep_element_index,
    grouped_deep_elements,
)


def field_observations(
    root: ET.Element,
    fields: dict[str, tuple[str, ...]],
    elements_by_tag: dict[str, list[ET.Element]] | None = None,
) -> dict[str, dict[str, int]]:
    observations: dict[str, dict[str, int]] = {}
    if elements_by_tag is None:
        elements_by_tag = deep_element_index(root)
    for field, names in fields.items():
        elements = grouped_deep_elements(elements_by_tag, names)
        populated = sum(
            any(part.strip() for part in element.itertext()) for element in elements
        )
        observations[field] = {
            "occurrences": len(elements),
            "populated_occurrences": populated,
            "blank_occurrences": len(elements) - populated,
        }
    return observations


def empty_field_observations(
    fields: dict[str, tuple[str, ...]],
) -> dict[str, dict[str, int]]:
    return {
        field: {
            "occurrences": 0,
            "populated_occurrences": 0,
            "blank_occurrences": 0,
        }
        for field in fields
    }


__all__ = ["empty_field_observations", "field_observations"]
