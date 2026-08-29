"""Entity normalization, structural token mining, and company family clustering.

Provides deterministic, two-pass company family resolution and classification
deduplication for Phase 02 target selection.
"""

from __future__ import annotations

import csv
import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from defs.regex import build_alternation

from .family_vocab import (
    ABBR_MAP,
    CONTEXT_RULES,
    HEAD_TOKENS,
    LEGAL_FORMS,
    MAX_PARENT_TOKENS,
    MIN_ALIAS_CHARS,
    MIN_CLUSTER_ATTACH,
    PLACEHOLDER,
    PLURAL_MAP,
    ROMAN,
    SEED,
    STATE_CODES,
    STRUCTURAL_THRESHOLD,
)

PUNCT_RE = re.compile(r"[/\\,._\-—()\[\]{}'\"’`&]+")
JURISDICTION_RE = re.compile(
    rf"\s*/\s*{build_alternation(STATE_CODES)}\s*/\s*",
    re.IGNORECASE,
)
TRADEMARK_RE = re.compile(
    rf"\({build_alternation(['sm', 'tm', 'r', 'c'])}\)", re.IGNORECASE
)


def normalize_name(name: str) -> list[str]:
    """Tokenize and normalize raw company name."""
    if not name:
        return []
    s = name.strip()
    s = JURISDICTION_RE.sub(" ", s)
    s = TRADEMARK_RE.sub(" ", s)
    s = PUNCT_RE.sub(" ", s).lower()

    raw_tokens = s.split()
    if not raw_tokens:
        return []

    tokens: list[str] = []
    for t in raw_tokens:
        if t in ABBR_MAP:
            expanded = ABBR_MAP[t]
            tokens.extend(expanded.split())
        else:
            tokens.append(t)

    refined: list[str] = []
    n = len(tokens)
    for i, t in enumerate(tokens):
        if t in CONTEXT_RULES:
            expansion, allowed_prev, allowed_next = CONTEXT_RULES[t]
            prev_t = tokens[i - 1] if i > 0 else ""
            next_t = tokens[i + 1] if i + 1 < n else ""
            prev_ok = not allowed_prev or prev_t in allowed_prev
            next_ok = not allowed_next or next_t in allowed_next
            if prev_ok and next_ok:
                refined.append(expansion)
            else:
                refined.append(t)
        else:
            refined.append(t)

    out: list[str] = []
    for t in refined:
        out.append(PLURAL_MAP.get(t, t))
    return out


def post_normalize(tokens: list[str]) -> list[str]:
    """Convert digits to D, single letters to S, romans to R."""
    out: list[str] = []
    for t in tokens:
        if t.isdigit():
            out.append("D")
        elif len(t) == 1 and t.isalpha():
            out.append("S")
        elif t.lower() in ROMAN:
            out.append("R")
        else:
            out.append(t)
    return out


def strip_legal_forms(tokens: list[str]) -> list[str]:
    """Remove legal and entity suffixes."""
    return [t for t in tokens if t not in LEGAL_FORMS]


def mine_structural_vocabulary(
    names: list[str],
    *,
    min_name_len: int = 6,
    head_tokens: int = HEAD_TOKENS,
    min_tail_freq: int | None = None,
    max_prefix_share: float = 0.35,
) -> set[str]:
    """Mine structural tail vocabulary with prefix share protection."""
    effective_min_tail = (
        min_tail_freq if min_tail_freq is not None else (8 if len(names) >= 100 else 1)
    )
    long_names = []
    for n in names:
        toks = strip_legal_forms(post_normalize(normalize_name(n)))
        if len(toks) >= (min_name_len if len(names) >= 100 else 3):
            long_names.append(toks)

    prefix_counts: Counter[str] = Counter()
    tail_counts: Counter[str] = Counter()
    for toks in long_names:
        for t in toks[:head_tokens]:
            if t not in PLACEHOLDER:
                prefix_counts[t] += 1
        for t in toks[head_tokens:]:
            if t not in PLACEHOLDER:
                tail_counts[t] += 1

    structural: set[str] = set()
    for token, t_cnt in tail_counts.items():
        if t_cnt < effective_min_tail:
            continue
        p_cnt = prefix_counts.get(token, 0)
        share = p_cnt / (p_cnt + t_cnt)
        if share < max_prefix_share:
            structural.add(token)

    return structural - LEGAL_FORMS


@dataclass(frozen=True)
class CompanyFamilyInfo:
    cik: str
    company_name: str
    family_id: str
    family_key: str
    representative_name: str
    is_variant: bool


class CompanyFamilyIndex:
    """Two-pass company family clustering and canonical resolver."""

    def __init__(
        self,
        structural_vocab: set[str],
        cik_to_info: dict[str, CompanyFamilyInfo],
        name_to_info: dict[str, CompanyFamilyInfo],
    ) -> None:
        self.structural_vocab = structural_vocab
        self._cik_to_info = cik_to_info
        self._name_to_info = name_to_info

    @classmethod
    def build_from_seed(
        cls,
        seed_path: str | Path,
        *,
        seed_string: str = SEED,
    ) -> CompanyFamilyIndex:
        """Build the index from uploads/cik-sec.csv."""
        p = Path(seed_path).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"seed CIK file not found: {p}")

        ciks: list[str] = []
        names: list[str] = []
        with p.open("r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                raw_cik = (row.get("cik") or "").strip()
                name = (row.get("name") or "").strip()
                if not raw_cik or not name:
                    continue
                digits = "".join(ch for ch in raw_cik if ch.isdigit())
                if digits:
                    ciks.append(f"{int(digits):010d}")
                    names.append(name)

        return cls.build_from_records(list(zip(ciks, names)), seed_string=seed_string)

    @classmethod
    def build_from_records(
        cls,
        records: list[tuple[str, str]],
        *,
        seed_string: str = SEED,
    ) -> CompanyFamilyIndex:
        """Build the index from (cik, name) tuples."""
        raw_names = [n for _, n in records]
        structural_vocab = mine_structural_vocabulary(raw_names)

        # Pass 1: Parse and classify
        pure_roots: list[dict[str, Any]] = []
        protected_roots: list[dict[str, Any]] = []
        variants: list[dict[str, Any]] = []
        orphans: list[dict[str, Any]] = []

        parsed_records: list[dict[str, Any]] = []
        for cik, name in records:
            norm = normalize_name(name)
            post = post_normalize(norm)
            body = strip_legal_forms(post)

            indices = [
                i for i, t in enumerate(body) if t in structural_vocab or t == "D"
            ]
            count = len(indices)
            first_idx = indices[0] if indices else len(body)
            key_tokens = body[:first_idx]
            clean_key = [t for t in key_tokens if t not in PLACEHOLDER]

            rec = {
                "cik": cik,
                "name": name,
                "body": body,
                "count": count,
                "clean_key": tuple(clean_key),
            }
            parsed_records.append(rec)

            if not body or not clean_key:
                orphans.append(rec)
            elif count == 0:
                pure_roots.append(rec)
            elif count <= STRUCTURAL_THRESHOLD:
                protected_roots.append(rec)
            else:
                variants.append(rec)

        # Pass 2: Cluster assembly
        head_clusters: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
        for v in variants:
            key = v["clean_key"]
            head = key[:2] if len(key) >= 2 else key
            head_clusters[head].append(v)

        alias_map: dict[tuple[str, ...], tuple[str, ...]] = {}
        for head in sorted(head_clusters.keys(), key=lambda h: (len(h), h)):
            if len(head) < 2:
                continue
            flat = "".join(head)
            if len(flat) < MIN_ALIAS_CHARS:
                continue
            candidates = []
            for other in head_clusters:
                if other == head or len(other) < 2:
                    continue
                other_flat = "".join(other)
                if other_flat.startswith(flat):
                    candidates.append(other)
            if len(candidates) == 1:
                alias_map[head] = candidates[0]

        resolved_clusters: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(
            list
        )
        for head, members in head_clusters.items():
            target = head
            visited = set()
            while target in alias_map and target not in visited:
                visited.add(target)
                target = alias_map[target]
            resolved_clusters[target].extend(members)

        root_members: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
        for r in pure_roots + protected_roots:
            key = r["clean_key"]
            if key:
                root_members[key].append(r)

        first_token_heads: dict[str, set[tuple[str, ...]]] = defaultdict(set)
        for head in resolved_clusters:
            if head:
                first_token_heads[head[0]].add(head)

        first_token_root_continuations: dict[str, set[tuple[str, ...]]] = defaultdict(
            set
        )
        for rk in root_members:
            if len(rk) >= 2:
                first_token_root_continuations[rk[0]].add(rk[1:])

        def single_token_root_may_join(
            rkey: tuple[str, ...], target: tuple[str, ...]
        ) -> bool:
            if len(rkey) != 1:
                return True
            tok = rkey[0]
            if len(first_token_heads.get(tok, set())) != 1:
                return False
            conts = first_token_root_continuations.get(tok, set())
            if not conts:
                return True
            return len(conts) == 1 and next(iter(conts)) == target[1:]

        family_members: dict[str, list[dict[str, Any]]] = defaultdict(list)
        family_roots: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for target, members in resolved_clusters.items():
            heads = {
                v["clean_key"][:2] if len(v["clean_key"]) >= 2 else v["clean_key"]
                for v in members
            }
            heads.add(target)
            family_key = " ".join(target)

            attach_candidates = []
            if len(members) >= MIN_CLUSTER_ATTACH:
                for rkey, rnames in root_members.items():
                    if not rkey or not single_token_root_may_join(rkey, target):
                        continue
                    for head in heads:
                        shared = 0
                        for a, b in zip(rkey, head):
                            if a != b:
                                break
                            shared += 1
                        inside = len(rkey) < len(head) and head[: len(rkey)] == rkey
                        head_in_root = (
                            len(head) <= len(rkey) and rkey[: len(head)] == head
                        )
                        if shared >= 2 or inside or head_in_root:
                            attach_candidates.append((rkey, rnames))
                            break

            for m in members:
                family_members[family_key].append(m)
            for _, rlist in attach_candidates:
                for r in rlist:
                    family_roots[family_key].append(r)

        cik_to_info: dict[str, CompanyFamilyInfo] = {}
        name_to_info: dict[str, CompanyFamilyInfo] = {}

        # Resolve representative and store mappings
        for fam_key, members in family_members.items():
            fid = hashlib.md5(fam_key.replace(" ", "").encode()).hexdigest()[:12]
            roots = family_roots.get(fam_key, [])

            # Choose representative
            rep_candidates = []
            for r in roots:
                rep_candidates.append(
                    (
                        0,
                        len(r["body"]),
                        hashlib.md5(f"{seed_string}{r['name']}".encode()).hexdigest(),
                        r["name"],
                    )
                )
            if not rep_candidates:
                for m in members:
                    is_parent = m["count"] == 0 or len(m["body"]) <= MAX_PARENT_TOKENS
                    prio = 1 if is_parent else 2
                    rep_candidates.append(
                        (
                            prio,
                            len(m["body"]),
                            hashlib.md5(
                                f"{seed_string}{m['name']}".encode()
                            ).hexdigest(),
                            m["name"],
                        )
                    )

            rep_candidates.sort()
            rep_name = rep_candidates[0][3] if rep_candidates else fam_key

            for m in members:
                info = CompanyFamilyInfo(
                    cik=m["cik"],
                    company_name=m["name"],
                    family_id=fid,
                    family_key=fam_key,
                    representative_name=rep_name,
                    is_variant=True,
                )
                cik_to_info[m["cik"]] = info
                name_to_info[m["name"].strip().lower()] = info

            for r in roots:
                if r["cik"] not in cik_to_info:
                    info = CompanyFamilyInfo(
                        cik=r["cik"],
                        company_name=r["name"],
                        family_id=fid,
                        family_key=fam_key,
                        representative_name=rep_name,
                        is_variant=False,
                    )
                    cik_to_info[r["cik"]] = info
                    name_to_info[r["name"].strip().lower()] = info

        # Roots that were not clustered into variants stay as standalone root families
        for r in pure_roots + protected_roots + orphans:
            cik = r["cik"]
            if cik in cik_to_info:
                continue
            clean_k = (
                " ".join(r["clean_key"])
                if r["clean_key"]
                else r["name"].strip().lower()
            )
            fid = hashlib.md5(clean_k.replace(" ", "").encode()).hexdigest()[:12]
            info = CompanyFamilyInfo(
                cik=cik,
                company_name=r["name"],
                family_id=fid,
                family_key=clean_k,
                representative_name=r["name"],
                is_variant=False,
            )
            cik_to_info[cik] = info
            name_to_info[r["name"].strip().lower()] = info

        return cls(structural_vocab, cik_to_info, name_to_info)

    def resolve(self, cik: str, company_name: str = "") -> CompanyFamilyInfo:
        """Resolve CIK or company name to CompanyFamilyInfo."""
        normalized_cik = (
            f"{int(''.join(c for c in cik if c.isdigit())):010d}"
            if any(c.isdigit() for c in cik)
            else cik
        )
        if normalized_cik in self._cik_to_info:
            return self._cik_to_info[normalized_cik]
        if company_name:
            n_key = company_name.strip().lower()
            if n_key in self._name_to_info:
                return self._name_to_info[n_key]

        # Stateless fallback derivation
        derived_key = self.derive_company_family(company_name or cik)
        fid = hashlib.md5(derived_key.replace(" ", "").encode()).hexdigest()[:12]
        return CompanyFamilyInfo(
            cik=normalized_cik,
            company_name=company_name,
            family_id=fid,
            family_key=derived_key,
            representative_name=company_name or derived_key,
            is_variant=False,
        )

    def derive_company_family(self, name: str) -> str:
        """Stateless single-name fallback deriver."""
        if not name:
            return ""
        norm = normalize_name(name)
        post = post_normalize(norm)
        body = strip_legal_forms(post)
        if not body:
            return name.strip().lower()

        indices = [
            i for i, t in enumerate(body) if t in self.structural_vocab or t == "D"
        ]
        count = len(indices)
        if count <= STRUCTURAL_THRESHOLD:
            clean = [t for t in body if t not in PLACEHOLDER]
            return " ".join(clean) if clean else " ".join(body)

        first_idx = indices[0] if indices else len(body)
        key_tokens = body[:first_idx]
        clean_key = [t for t in key_tokens if t not in PLACEHOLDER]
        if clean_key:
            head = clean_key[:2] if len(clean_key) >= 2 else clean_key
            return " ".join(head)
        return " ".join(body[:2]) if len(body) >= 2 else " ".join(body)


__all__ = [
    "ABBR_MAP",
    "CONTEXT_RULES",
    "LEGAL_FORMS",
    "PLURAL_MAP",
    "CompanyFamilyIndex",
    "CompanyFamilyInfo",
    "mine_structural_vocabulary",
    "normalize_name",
    "post_normalize",
    "strip_legal_forms",
]
