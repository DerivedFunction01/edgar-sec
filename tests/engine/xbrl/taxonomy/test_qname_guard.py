"""Standing guard: no new full-qname lookups in taxonomy data or engine code."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import re

from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths

QNAME = re.compile(r"^[a-z][a-z0-9-]*:[A-Z][A-Za-z0-9]+$")

# Sanctioned qname-shaped values in taxonomy data (Phase 0 sweep S5/S6):
# geography member identifiers are the member ontology itself, and each
# axis family's default axis is declared per family pattern.
JSON_FIELD_ALLOWLIST = {
    "geography_dag.json": None,  # None: every field is member ontology data.
    "axis_families.json": {"default_axis_qname"},
}

# Verified non-semantic qname uses in engine code (Phase 0 sweep R-e):
# instance_parser reconstructs namespace prefixes by string formatting,
# review/benchmark builds synthetic fixture facts, and solve/candidates
# tests namespace-class prefixes by comparison. None keys a dict by qname,
# so the permitted-key sets are empty: a future qname-keyed dict anywhere
# fails until its exact keys are named here.
DICT_KEY_ALLOWLIST: dict[str, set[str]] = {
    "engine/xbrl/parsing/instance_parser.py": set(),
    "engine/xbrl/review/benchmark.py": set(),
    "engine/xbrl/solve/candidates.py": set(),
}


def _strings(obj: object, field: str = ""):
    if isinstance(obj, str):
        yield field, obj
    elif isinstance(obj, dict):
        for key, value in obj.items():
            yield from _strings(key, field)
            yield from _strings(value, str(key))
    elif isinstance(obj, list):
        for value in obj:
            yield from _strings(value, field)


def test_taxonomy_json_carries_no_qname_literals() -> None:
    """Taxonomy JSON values are coordinates/patterns, never concept qnames."""
    taxonomy_dir = resolve_xbrl_paths().default_taxonomy_dir
    violations: list[str] = []
    for path in sorted(taxonomy_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        allowed = JSON_FIELD_ALLOWLIST.get(path.name, set())
        for field, value in _strings(data):
            if not QNAME.match(value):
                continue
            if allowed is None or field in allowed:
                continue
            violations.append(f"{path.name}:{field}={value}")
    assert not violations, violations


def test_engine_code_has_no_qname_keyed_dicts() -> None:
    """No dict literal in the XBRL engine may be keyed by a concept qname."""
    root = resolve_xbrl_paths().repo_root
    engine_dir = root / "edgar_sec" / "engine" / "xbrl"
    violations: list[str] = []
    for path in sorted(engine_dir.rglob("*.py")):
        rel = path.relative_to(root / "edgar_sec").as_posix()
        permitted = DICT_KEY_ALLOWLIST.get(rel, set())
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key in node.keys:
                if (
                    isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    and QNAME.match(key.value)
                    and key.value not in permitted
                ):
                    violations.append(f"{rel}:{node.lineno} key={key.value}")
    assert not violations, violations


def test_guard_patterns_are_live() -> None:
    """The qname pattern itself matches the shapes the guard exists to ban."""
    assert QNAME.match("us-gaap:Revenues")
    assert QNAME.match("dei:CoverAbstract")
    assert not QNAME.match("us-gaap:us-gaap")
    assert not QNAME.match("H_REVENUE")
    assert Path(resolve_xbrl_paths().default_taxonomy_dir).is_dir()
