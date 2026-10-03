"""Two-pass company-family clustering and canonical resolution.

The problem: one economic entity files under many CIKs. A mortgage trust files
once per deal, each with a different CIK and a name differing only in the series
number. Left alone, a single corporate family swamps any quota-based sample, so
research drawn from it inherits one company's filing history.

The approach is two passes over a registrant corpus. The first classifies each
name as a pure root, a protected root, a series variant, or an orphan, and mines
the structural tail vocabulary that separates "Santander Drive Auto Receivables
Trust 2007-2" from "Santander Drive Auto Receivables Trust 2013-2". The second
assembles variants into families keyed on their shared head, resolves head
aliases, and attaches plausible parent registrants.

Everything is in-memory and deterministic: no I/O beyond the one explicit
factory method, and no dependence on dict ordering or wall-clock state.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from edgar_sec.domain.sec_urls import normalize_cik
from edgar_sec.domain.taxonomy.family_vocab import (
    MIN_ALIAS_CHARS,
    MIN_CLUSTER_ATTACH,
    PLACEHOLDER,
    SEED,
)
from edgar_sec.engine.company_family.normalizer import (
    clean_key,
    count_structural_tokens,
    first_structural_index,
    is_plausible_parent,
    is_variant,
    mine_structural_vocabulary,
    normalize_name,
    normalized_body,
    post_normalize,
    strip_legal_forms,
)

FAMILY_ID_LENGTH = 12


@dataclass(frozen=True, slots=True)
class CompanyFamilyInfo:
    """Resolved family membership for one registrant."""

    cik: str
    company_name: str
    family_id: str
    family_key: str
    representative_name: str
    is_variant: bool


def family_id_for(family_key: str) -> str:
    """Return the short, stable id for a family key.

    SHA-256 rather than MD5: this is a content digest used as a display id, not
    a security primitive, and there is no reason to reach for a broken hash.
    Changing the algorithm changes every derived id, which is why it is pinned
    here rather than inlined at the call sites.
    """
    compact = family_key.replace(" ", "")
    return hashlib.sha256(compact.encode()).hexdigest()[:FAMILY_ID_LENGTH]


def _representative_rank(
    record: dict[str, Any], seed_string: str
) -> tuple[int, int, str, str]:
    """Order candidates so the most parent-like name wins, deterministically.

    The trailing hash of the seed and the name breaks remaining ties by value
    rather than by arrival order, so the representative is stable no matter how
    the corpus was ordered.
    """
    if record["count"] == 0:
        priority = 0
    elif is_plausible_parent(record["body"]):
        priority = 1
    else:
        priority = 2
    return (
        priority,
        len(record["body"]),
        hashlib.sha256(f"{seed_string}{record['name']}".encode()).hexdigest(),
        record["name"],
    )


class CompanyFamilyIndex:
    """Two-pass company family clustering and canonical resolver."""

    __slots__ = ("_cik_to_info", "_name_to_info", "structural_vocab")

    def __init__(
        self,
        structural_vocab: frozenset[str] | set[str],
        cik_to_info: dict[str, CompanyFamilyInfo],
        name_to_info: dict[str, CompanyFamilyInfo],
    ) -> None:
        # Frozen after construction: the index is a lookup structure, and a
        # caller mutating it mid-resolution would make results depend on order.
        self.structural_vocab = frozenset(structural_vocab)
        self._cik_to_info = MappingProxyType(cik_to_info)
        self._name_to_info = MappingProxyType(name_to_info)

    # -------------------------------------------------------------- factories

    @property
    def cik_to_info(self) -> Mapping[str, CompanyFamilyInfo]:
        """The resolved registrant-to-family mapping, read-only.

        A consumer that needs every resolved registrant -- to load the families
        into a query engine, for instance -- needs no second pass over the corpus.
        """
        return self._cik_to_info

    @classmethod
    def from_existing_profiles(
        cls,
        profiles_path: str | Path,
        *,
        seed_string: str = SEED,
    ) -> CompanyFamilyIndex:
        """Build the index from a materialized ``company_profiles.parquet``."""
        from edgar_sec.infra.storage.duckdb import connect
        from edgar_sec.infra.storage.duckdb_catalog import sql_literal

        path = Path(profiles_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"company profiles file not found: {path}")

        records: list[tuple[str, str]] = []
        with connect() as con:
            rows = con.execute(
                "SELECT cik, identity.name FROM "
                f"read_parquet({sql_literal(str(path))}) WHERE cik IS NOT NULL"
            ).fetchall()
        for raw_cik, name in rows:
            if raw_cik and name:
                digits = "".join(ch for ch in str(raw_cik) if ch.isdigit())
                if digits:
                    records.append((normalize_cik(digits), str(name)))
        return cls.build_from_records(records, seed_string=seed_string)

    @classmethod
    def build_from_records(
        cls,
        records: Sequence[tuple[str, str]],
        *,
        seed_string: str = SEED,
    ) -> CompanyFamilyIndex:
        """Build the index from ``(cik, company_name)`` pairs."""
        raw_names = [name for _, name in records]
        structural_vocab = mine_structural_vocabulary(raw_names)

        # -- Pass 1: classify every record -------------------------------
        pure_roots: list[dict[str, Any]] = []
        protected_roots: list[dict[str, Any]] = []
        variants: list[dict[str, Any]] = []
        orphans: list[dict[str, Any]] = []

        for cik, name in records:
            body = normalized_body(name)
            structural = count_structural_tokens(body, structural_vocab)
            key = clean_key(body, structural_vocab)
            record: dict[str, Any] = {
                "cik": cik,
                "name": name,
                "body": body,
                "count": structural,
                "clean_key": key,
            }
            if not body or not key:
                orphans.append(record)
            elif structural == 0:
                pure_roots.append(record)
            elif is_variant(body, structural_vocab):
                variants.append(record)
            else:
                protected_roots.append(record)

        # -- Pass 2: assemble clusters -----------------------------------
        head_clusters: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
        for variant in variants:
            key = variant["clean_key"]
            head = key[:2] if len(key) >= 2 else key
            head_clusters[head].append(variant)

        alias_map = _resolve_head_aliases(head_clusters)

        resolved_clusters: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(
            list
        )
        for head, members in head_clusters.items():
            target = head
            visited: set[tuple[str, ...]] = set()
            # Alias chains are followed to a fixed point, guarding against a
            # cycle introduced by a later alias assignment.
            while target in alias_map and target not in visited:
                visited.add(target)
                target = alias_map[target]
            resolved_clusters[target].extend(members)

        root_members: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
        for record in [*pure_roots, *protected_roots]:
            if record["clean_key"]:
                root_members[record["clean_key"]].append(record)

        attachable = _attach_roots(resolved_clusters, root_members)

        cik_to_info: dict[str, CompanyFamilyInfo] = {}
        name_to_info: dict[str, CompanyFamilyInfo] = {}

        for target, members in resolved_clusters.items():
            family_key = " ".join(target)
            fid = family_id_for(family_key)
            roots = attachable.get(family_key, [])
            rep_name = _choose_representative(roots, members, family_key, seed_string)
            for member in members:
                _register(
                    cik_to_info, name_to_info, member, fid, family_key, rep_name, True
                )
            for root in roots:
                if root["cik"] not in cik_to_info:
                    _register(
                        cik_to_info,
                        name_to_info,
                        root,
                        fid,
                        family_key,
                        rep_name,
                        False,
                    )

        # Standalone registrants: roots and orphans that joined no family.
        for record in [*pure_roots, *protected_roots, *orphans]:
            if record["cik"] in cik_to_info:
                continue
            key = record["clean_key"]
            family_key = " ".join(key) if key else record["name"].strip().lower()
            info = CompanyFamilyInfo(
                cik=record["cik"],
                company_name=record["name"],
                family_id=family_id_for(family_key),
                family_key=family_key,
                representative_name=record["name"],
                is_variant=False,
            )
            cik_to_info[record["cik"]] = info
            name_to_info[record["name"].strip().lower()] = info

        return cls(structural_vocab, cik_to_info, name_to_info)

    # ---------------------------------------------------------------- lookups

    def resolve(self, cik: str, company_name: str = "") -> CompanyFamilyInfo:
        """Resolve a CIK or company name, falling back to stateless derivation.

        The fallback matters: the selection features builder walks every filing
        in the catalog, and the catalog can name registrants that were absent
        from the seed manifest. Returning a derived key keeps those rows usable
        instead of dropping them.
        """
        normalized = normalize_cik(cik) if any(c.isdigit() for c in cik) else cik
        found = self._cik_to_info.get(normalized)
        if found is not None:
            return found
        if company_name:
            found = self._name_to_info.get(company_name.strip().lower())
            if found is not None:
                return found

        derived_key = self.derive_company_family(company_name or cik)
        return CompanyFamilyInfo(
            cik=normalized,
            company_name=company_name,
            family_id=family_id_for(derived_key),
            family_key=derived_key,
            representative_name=company_name or derived_key,
            is_variant=False,
        )

    def derive_company_family(self, name: str) -> str:
        """Derive a family key from a single name, with no corpus context."""
        if not name:
            return ""
        body = strip_legal_forms(post_normalize(normalize_name(name)))
        if not body:
            return name.strip().lower()

        structural = count_structural_tokens(body, self.structural_vocab)
        if structural <= _structural_threshold():
            clean = [token for token in body if token not in PLACEHOLDER]
            return " ".join(clean) if clean else " ".join(body)

        boundary = first_structural_index(body, self.structural_vocab)
        key = tuple(t for t in body[:boundary] if t not in PLACEHOLDER)
        if key:
            head = key[:2] if len(key) >= 2 else key
            return " ".join(head)
        return " ".join(body[:2]) if len(body) >= 2 else " ".join(body)

    def __len__(self) -> int:
        return len(self._cik_to_info)


def _structural_threshold() -> int:
    from edgar_sec.domain.taxonomy.family_vocab import STRUCTURAL_THRESHOLD

    return STRUCTURAL_THRESHOLD


def _resolve_head_aliases(
    head_clusters: dict[tuple[str, ...], list[dict[str, Any]]],
) -> dict[tuple[str, ...], tuple[str, ...]]:
    """Alias a short head to a single longer head that extends it.

    A head aliases only when exactly one candidate extends it. When several
    do, the resemblance is ambiguous and merging them would join unrelated
    companies, so neither is aliased.
    """
    alias_map: dict[tuple[str, ...], tuple[str, ...]] = {}
    for head in sorted(head_clusters, key=lambda h: (len(h), h)):
        if len(head) < 2 or len("".join(head)) < MIN_ALIAS_CHARS:
            continue
        flat = "".join(head)
        candidates = [
            other
            for other in head_clusters
            if other != head and len(other) >= 2 and "".join(other).startswith(flat)
        ]
        if len(candidates) == 1:
            alias_map[head] = candidates[0]
    return alias_map


def _shared_prefix_length(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    shared = 0
    for a, b in zip(left, right):
        if a != b:
            break
        shared += 1
    return shared


def _attach_roots(
    resolved_clusters: dict[tuple[str, ...], list[dict[str, Any]]],
    root_members: dict[tuple[str, ...], list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Attach parent registrants to a family when the evidence is strong.

    Three conditions qualify: a two-token shared prefix, a root strictly
    inside a head, or a head that is a prefix of the root. A single shared
    token is explicitly *not* enough -- that is what keeps "Honda Motor" and
    "Honda Auto" apart.
    """
    first_token_heads: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    for head in resolved_clusters:
        if head:
            first_token_heads[head[0]].add(head)

    first_token_root_continuations: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    for root_key in root_members:
        if len(root_key) >= 2:
            first_token_root_continuations[root_key[0]].add(root_key[1:])

    def single_token_root_may_join(
        root_key: tuple[str, ...], target: tuple[str, ...]
    ) -> bool:
        if len(root_key) != 1:
            return True
        token = root_key[0]
        # If the token heads more than one family, the root is ambiguous.
        if len(first_token_heads.get(token, set())) != 1:
            return False
        continuations = first_token_root_continuations.get(token, set())
        if not continuations:
            return True
        return len(continuations) == 1 and next(iter(continuations)) == target[1:]

    attachable: dict[str, list[dict[str, Any]]] = {}
    for target, members in resolved_clusters.items():
        if len(members) < MIN_CLUSTER_ATTACH:
            continue
        heads = {
            m["clean_key"][:2] if len(m["clean_key"]) >= 2 else m["clean_key"]
            for m in members
        }
        heads.add(target)
        collected: list[dict[str, Any]] = []
        for root_key, roots in root_members.items():
            if not root_key or not single_token_root_may_join(root_key, target):
                continue
            for head in heads:
                shared = _shared_prefix_length(root_key, head)
                inside = len(root_key) < len(head) and head[: len(root_key)] == root_key
                head_in_root = (
                    len(head) <= len(root_key) and root_key[: len(head)] == head
                )
                if shared >= 2 or inside or head_in_root:
                    collected.extend(roots)
                    break
        if collected:
            attachable[" ".join(target)] = collected
    return attachable


def _choose_representative(
    roots: Sequence[dict[str, Any]],
    members: Sequence[dict[str, Any]],
    family_key: str,
    seed_string: str,
) -> str:
    """Pick the family representative, preferring an attached parent."""
    candidates = [_representative_rank(r, seed_string) for r in roots] or [
        _representative_rank(m, seed_string) for m in members
    ]
    if not candidates:
        return family_key
    candidates.sort()
    return candidates[0][3]


def _register(
    cik_to_info: dict[str, CompanyFamilyInfo],
    name_to_info: dict[str, CompanyFamilyInfo],
    record: dict[str, Any],
    fid: str,
    family_key: str,
    rep_name: str,
    is_variant: bool,
) -> None:
    info = CompanyFamilyInfo(
        cik=record["cik"],
        company_name=record["name"],
        family_id=fid,
        family_key=family_key,
        representative_name=rep_name,
        is_variant=is_variant,
    )
    cik_to_info[record["cik"]] = info
    name_to_info[record["name"].strip().lower()] = info


__all__ = [
    "FAMILY_ID_LENGTH",
    "CompanyFamilyIndex",
    "CompanyFamilyInfo",
    "family_id_for",
]
