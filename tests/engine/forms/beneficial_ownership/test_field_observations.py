from __future__ import annotations

import xml.etree.ElementTree as ET

from edgar_sec.engine.forms.beneficial_ownership.field_observations import (
    empty_field_observations,
    field_observations,
)


def test_field_observations_counts_occurrences_and_populated_values() -> None:
    root = ET.fromstring("<root><name>Alice</name><name/><other>Bob</other></root>")
    fields = {"name": ("name",), "phone": ("phone",)}

    assert field_observations(root, fields) == {
        "name": {
            "occurrences": 2,
            "populated_occurrences": 1,
            "blank_occurrences": 1,
        },
        "phone": {
            "occurrences": 0,
            "populated_occurrences": 0,
            "blank_occurrences": 0,
        },
    }
    assert empty_field_observations(fields)["name"]["occurrences"] == 0
