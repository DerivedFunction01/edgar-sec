"""Section corpus: the detector over banked normalized text, per specimen.

Banking and conventions: the corpus README beside the fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_sec.domain.forms.common.models import ItemDefinition
from edgar_sec.engine.forms.sections.items.detector import detect_section_sequence
from tests.support.fixtures import fixture_path

_CORPUS = fixture_path("engine/forms/sections/section_corpus")

# Families whose profiles opt into run-in section titles; the corpus
# builder (edgar_sec.tools.section_corpus) applies the same convention.
_RUN_IN_FAMILIES = frozenset({"form_n23c3"})


def _taxonomies() -> dict[str, tuple[ItemDefinition, ...]]:
    raw = json.loads((_CORPUS / "taxonomies.json").read_text(encoding="utf-8"))
    return {
        slug: tuple(
            ItemDefinition(
                item=it["item"],
                part=it["part"],
                names=tuple(it["names"]),
                optional=it["optional"],
                early=it["early"],
            )
            for it in items
        )
        for slug, items in raw.items()
    }


_TAXONOMIES = _taxonomies()
_INDEX = json.loads((_CORPUS / "index.json").read_text(encoding="utf-8"))

# Specimens whose texts the re-proof showed regenerable from the EDGAR
# archives on the corpus builder are not tracked; the registry beside
# the index names each one with its banked hash, and regen_check.py
# (beside the corpus) re-verifies them in the tooling layer.
_DROPPED_PATH = _CORPUS / "dropped_texts.json"
_DROPPED: dict[str, dict] = (
    {e["id"]: e for e in json.loads(_DROPPED_PATH.read_text(encoding="utf-8"))}
    if _DROPPED_PATH.exists()
    else {}
)
_LIVE = [e for e in _INDEX if e["id"] not in _DROPPED]


@pytest.mark.parametrize("entry", _LIVE, ids=[e["id"] for e in _LIVE])
def test_specimen_resolutions_match_expectations(entry: dict) -> None:
    text = (_CORPUS / entry["text"]).read_text(encoding="utf-8")
    toc_span = tuple(entry["toc_span"]) if entry["toc_span"] else None
    seq = detect_section_sequence(
        text,
        family=entry["family"],
        taxonomy_items=_TAXONOMIES[entry["family"]],
        toc_span=toc_span,
        run_in_titles=entry["family"] in _RUN_IN_FAMILIES,
    )
    assert [s.item_identifier for s in seq.sections] == entry["expected"]


def test_corpus_index_is_complete_and_consistent() -> None:
    ids = [e["id"] for e in _INDEX]
    assert len(ids) == len(set(ids))
    for entry in _LIVE:
        assert entry["family"] in _TAXONOMIES
        text_path = _CORPUS / entry["text"]
        assert text_path.is_file() and text_path.stat().st_size > 0
        assert Path(entry["text"]).name == f"{entry['accession']}__{entry['document']}"
    by_id = {e["id"]: e for e in _INDEX}
    for entry_id, dropped in _DROPPED.items():
        assert entry_id in by_id
        assert dropped["text"] == by_id[entry_id]["text"]
        assert not (_CORPUS / dropped["text"]).exists()
