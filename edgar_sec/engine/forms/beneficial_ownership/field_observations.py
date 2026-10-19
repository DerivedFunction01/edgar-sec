from __future__ import annotations

import xml.etree.ElementTree as ET


def field_observations(
    root: ET.Element, fields: dict[str, tuple[str, ...]]
) -> dict[str, dict[str, int]]:
    observations: dict[str, dict[str, int]] = {}
    for field, names in fields.items():
        wanted = set(names)
        elements = [
            element
            for element in root.iter()
            if element.tag.rsplit("}", 1)[-1] in wanted
        ]
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
