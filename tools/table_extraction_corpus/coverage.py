"""Coverage machinery: retired-taxonomy inventory and seed candidates.

Extracts the pre-retire taxonomy's family inventory from git history and
builds seed-candidate evidence (hypotheses) for successor families that
lack standing registry evidence. Measurement, not this module, arbitrates.
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import importlib
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from edgar_sec.engine.tables.extraction.normalize import normalize_text

RETIRED_REF = "06af1209"

TARGET_FAMILIES = (
    "aoci",
    "cover_layout",
    "debt_maturity",
    "derivatives_hedging",
    "equity_statement",
    "intangibles",
    "pension",
    "ppe",
    "shares_purchased",
    "stock_comp_rollforward",
)

# Specs whose compiled packs are compound cross-products: their seed
# phrases come from source literals, not the expanded term lists.
LITERAL_MODULES = {
    "derivatives_hedging": (
        "schedules/derivatives/bases.py",
        "schedules/derivatives/cp.py",
        "schedules/derivatives/credit.py",
        "schedules/derivatives/eq.py",
        "schedules/derivatives/fx.py",
        "schedules/derivatives/generic.py",
        "schedules/derivatives/spec.py",
    ),
    "labor_contracts": ("schedules/labor.py",),
    "legal_proceedings": ("schedules/legal.py",),
}

MINING_ONLY = ("labor_contracts", "legal_proceedings")
MAX_COMPILED_TOKENS = 3


def phrase_forms(phrase: str) -> set[str]:
    """Return the matchable forms of one seed phrase."""
    normalized = normalize_text(phrase)
    if not normalized:
        return set()
    forms = {normalized}
    tokens = normalized.split()
    if len(tokens) >= 2:
        forms.update(f"{a} {b}" for a, b in zip(tokens, tokens[1:], strict=False))
        forms.update(token for token in tokens if len(token) >= 3)
    return forms


def module_literals(source: str) -> list[str]:
    """Harvest term-like string literals from a module's source."""
    tree = ast.parse(source)
    docstring_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                docstring_ids.add(id(node.body[0].value))
    found = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in docstring_ids:
            continue
        text = normalize_text(node.value)
        words = text.split()
        if 1 <= len(words) <= 6 and len(text) >= 3 and any(c.isalpha() for c in text):
            found.add(text)
    return sorted(found)


def _tier_phrases(
    spec: dict, *, primary_only: bool = False
) -> list[tuple[str, str, bool]]:
    phrases = []
    for tier in spec["tiers"]:
        if primary_only and tier["support"]:
            continue
        for term in tier["terms"]:
            if len(term.split()) <= MAX_COMPILED_TOKENS:
                phrases.append((term, tier["name"], bool(tier["support"])))
    return phrases


def build_seed_candidates(inventory: dict) -> dict:
    """Build per-family seed-candidate forms from a retired inventory."""
    specs = inventory["specs"]
    literals = inventory.get("literals", {})
    families: dict[str, dict] = {}
    for family in TARGET_FAMILIES:
        spec = specs[family]
        origins: dict[str, dict] = {}
        if family in LITERAL_MODULES:
            phrases = [(text, "source-literals", False) for text in literals[family]]
        else:
            phrases = _tier_phrases(spec)
        for phrase, tier, support_tier in phrases:
            for form in phrase_forms(phrase):
                origin = origins.setdefault(form, {"phrases": set(), "tiers": set()})
                origin["phrases"].add(phrase)
                origin["tiers"].add(tier)
        families[family] = {
            "retired_spec": family,
            "source": spec["source"],
            "exclusions": spec["exclusions"],
            "forms": {
                form: {
                    "phrases": sorted(origin["phrases"]),
                    "tiers": sorted(origin["tiers"]),
                }
                for form, origin in sorted(origins.items())
            },
        }
    mining: dict[str, dict] = {}
    for family in MINING_ONLY:
        phrases = set(literals.get(family, ()))
        if family in specs:
            phrases.update(
                phrase
                for phrase, _, _ in _tier_phrases(specs[family], primary_only=True)
            )
        mining[family] = {"phrases": sorted(phrases)}
    return {"families": families, "mining": mining}


def _spec_json(spec, source: str) -> dict:
    pack = spec.evidence_pack
    tiers = []
    for tier in getattr(pack, "tiers", ()):
        terms = sorted(getattr(tier, "unigrams", ()))
        ngram_index = getattr(tier, "ngram_index", None) or {}
        for length in sorted(ngram_index):
            terms.extend(" ".join(tok) for tok in sorted(ngram_index[length]))
        tiers.append(
            {
                "name": tier.name,
                "match_kind": tier.match_kind,
                "support": bool(getattr(tier, "support", False)),
                "value": getattr(tier, "value", None),
                "priority": getattr(tier, "priority", None),
                "min_distinct_hits": getattr(tier, "min_distinct_hits", None),
                "terms": terms,
            }
        )
    return {
        "name": spec.name,
        "source": source,
        "priority": spec.priority,
        "scope": str(spec.candidate_default_scope),
        "repair_policy": str(spec.repair_policy),
        "shape": dataclasses.asdict(spec.shape),
        "exclusions": sorted(getattr(pack, "exclusions", ())),
        "tiers": tiers,
    }


def extract_inventory(repo: Path, ref: str = RETIRED_REF) -> dict:
    """Extract the retired inventory by importing the ref's own modules."""
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "tree.tar"
        with archive.open("wb") as handle:
            subprocess.run(
                ["git", "-C", str(repo), "archive", ref, "edgar_sec"],
                stdout=handle,
                check=True,
            )
        with tarfile.open(archive) as tar:
            tar.extractall(Path(tmp), filter="data")
        root = Path(tmp)
        sys.path.insert(0, str(root))
        try:
            from edgar_sec.domain.taxonomy.tables.families import FAMILY_SPECS
            from edgar_sec.domain.taxonomy.tables.specs import TableFamilySpec

            specs = {
                name: _spec_json(spec, "tables/families.py FAMILY_SPECS")
                for name, spec in sorted(FAMILY_SPECS.items())
            }
            literals: dict[str, list[str]] = {}
            base = root / "edgar_sec" / "domain" / "taxonomy"
            for family, relatives in LITERAL_MODULES.items():
                harvested: set[str] = set()
                for relative in relatives:
                    harvested.update(module_literals((base / relative).read_text()))
                literals[family] = sorted(harvested)
            return {"ref": ref, "specs": specs, "literals": literals}
        finally:
            sys.path.remove(str(root))


def main(argv: list[str] | None = None) -> int:
    """Run the coverage machinery CLI (inventory, seeds)."""
    parser = argparse.ArgumentParser(prog="coverage")
    sub = parser.add_subparsers(dest="command", required=True)
    inv = sub.add_parser("inventory")
    inv.add_argument("--repo", type=Path, required=True)
    inv.add_argument("--ref", default=RETIRED_REF)
    inv.add_argument("--out", type=Path, required=True)
    seeds = sub.add_parser("seeds")
    seeds.add_argument("--inventory", type=Path, required=True)
    seeds.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "inventory":
        payload = extract_inventory(args.repo, args.ref)
    else:
        payload = build_seed_candidates(json.loads(args.inventory.read_text()))
    args.out.write_text(json.dumps(payload, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
