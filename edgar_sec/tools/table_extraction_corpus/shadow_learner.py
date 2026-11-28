"""ML-shadow learner over the imposter-census priced feature space.

Per family, enumerates conjunctions of census-feature atoms and
gini decision-tree leaf paths against the census residual falses,
and certifies the learned separations the held-out split supports.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path

from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.tools.table_extraction_corpus.census_pricing import (
    specimen_features,
)

_CONT_KEYS = ("n_rows", "n_cols", "num_share", "pct_share", "move_density")


def parse_residual_lists(lines) -> dict:
    """Residual specimen ids per family from residual-lists lines."""
    resid = {}
    cur = None
    for ln in lines:
        ln = ln.rstrip("\n")
        if ln.startswith("## "):
            cur = ln.split()[1]
            resid[cur] = []
        elif ln.strip() and cur:
            resid[cur].append(ln.split("|")[0].strip())
    return resid


def _family_features(rows: list[dict]) -> dict:
    """Per-family specimen features, host features included."""
    fams = defaultdict(lambda: {"false": [], "true": []})
    for r in rows:
        if r["text_source"] is None:
            continue
        side = "false" if r["side"] == "false" else "true"
        fams[r["family"]][side].append(r)
    famdata = {}
    for fam in sorted(fams):
        falses, trues = fams[fam]["false"], fams[fam]["true"]
        if not falses and not trues:
            continue
        feat = {}
        for r in falses + trues:
            feat[r["sid"]] = specimen_features(r)
        tcount = Counter()
        for r in trues:
            for k in set(feat[r["sid"]]["_stub_keys"]):
                tcount[k] += 1
        n_t = max(1, len(trues))
        core_strong = sorted(k for k, c in tcount.items() if c >= 0.5 * n_t)
        famdata[fam] = {
            "F": [r["sid"] for r in falses],
            "T": [r["sid"] for r in trues],
            "feat": feat,
            "core_strong": core_strong,
        }
    strong = {f: set(d["core_strong"]) for f, d in famdata.items()}
    for fam, d in famdata.items():
        for sid, f in d["feat"].items():
            keys = set(f["_stub_keys"])
            for other, vocab in strong.items():
                if other != fam and vocab:
                    inter = len(keys & vocab)
                    if inter >= 2:
                        f[f"host:{other}"] = 1
                    if inter >= 1:
                        f[f"host1:{other}"] = 1
    return famdata


def _structural_atoms(feat: dict, sids: list) -> dict:
    """Structural threshold atoms, cut at every observed value."""
    atoms = {}
    for name, key, sense in (
        ("rows_le", "n_rows", "le"),
        ("numshare_ge", "num_share", "ge"),
        ("pctshare_ge", "pct_share", "ge"),
        ("movedens_le", "move_density", "le"),
    ):
        vals = sorted({feat[s][key] for s in sids})
        for v in vals:
            if sense == "le":
                ks = {s for s in sids if feat[s][key] <= v}
            else:
                ks = {s for s in sids if feat[s][key] >= v}
            if 0 < len(ks) < len(sids):
                atoms[f"{name}_{v}"] = ks
    return atoms


def _build_atoms(feat: dict, falses: list, trues: list) -> dict:
    """Atom name to kill set: A present, B absent (core-carried)."""
    sids = falses + trues
    atoms = {}
    universe = Counter()
    for s in sids:
        for k, v in feat[s].items():
            if k.startswith("_") or k in _CONT_KEYS:
                continue
            if v:
                universe[k] += 1
    for name in universe:
        atoms[f"A:{name}"] = {s for s in sids if feat[s].get(name)}
    if trues:
        for name in universe:
            carried_t = sum(1 for s in trues if feat[s].get(name))
            if carried_t >= 0.5 * len(trues):
                atoms[f"B:{name}"] = {s for s in sids if not feat[s].get(name)}
    for name, ks in _structural_atoms(feat, sids).items():
        atoms[f"A:{name}"] = ks
    return atoms


def _half_of(sid: str) -> int:
    """The deterministic held-out split: sha1(sid) parity."""
    return int(hashlib.sha1(sid.encode()).hexdigest()[:8], 16) % 2


def _conjunction_kill(steps, atoms: dict, sids: list) -> set:
    """Specimens killed by a conjunction of (polarity, atom) steps."""
    ks = set(sids)
    for pol, a in steps:
        base = atoms[a]
        ks &= base if pol == "is" else (set(sids) - base)
    return ks


def _gini_paths(atoms: dict, pos: set, neg: set, max_depth=3, min_leaf=2):
    """False-side leaf paths of a depth-limited gini decision tree."""
    paths = []

    def impurity(p, n):
        tot = p + n
        if tot == 0:
            return 0.0
        pp, nn = p / tot, n / tot
        return 1 - pp * pp - nn * nn

    def split(specimens, depth, path):
        p = sum(1 for s in specimens if s in pos)
        n = len(specimens) - p
        if p and (n == 0 or depth == max_depth or len(specimens) < 2 * min_leaf):
            if p >= min_leaf and p > n:
                paths.append(list(path))
            return
        if not p or depth == max_depth or len(specimens) < 2 * min_leaf:
            return
        base = impurity(p, n) * len(specimens)
        best = None
        for name, ks in atoms.items():
            left = [s for s in specimens if s in ks]
            right = [s for s in specimens if s not in ks]
            if len(left) < min_leaf or len(right) < min_leaf:
                continue
            lp = sum(1 for s in left if s in pos)
            rp = p - lp
            gain = (
                base
                - impurity(lp, len(left) - lp) * len(left)
                - impurity(rp, len(right) - rp) * len(right)
            )
            if best is None or gain > best[0]:
                best = (gain, name, left, right)
        if best is None or best[0] <= 0:
            if p >= min_leaf and p > n:
                paths.append(list(path))
            return
        _g, name, left, right = best
        split(left, depth + 1, path + [name])
        split(right, depth + 1, path + [f"~{name}"])

    split(sorted(pos) + sorted(neg), 0, [])
    out = []
    for pth in paths:
        conj = []
        for step in pth:
            if step.startswith("~"):
                conj.append(("not", step[1:]))
            else:
                conj.append(("is", step))
        out.append(conj)
    return out


def _family_candidates(feat: dict, falses: list, trues: list, targets, budget):
    """Candidates priced across both held-out directions."""
    atoms_full = _build_atoms(feat, falses, trues)
    tset = set(trues)
    target_set = set(targets)
    full_touch = {a: len(ks & tset) for a, ks in atoms_full.items()}
    cand = {}
    for h in (0, 1):
        d_f = [s for s in targets if _half_of(s) == h]
        d_t = [s for s in trues if _half_of(s) == h]
        e_f = [s for s in targets if _half_of(s) != h]
        e_t = [s for s in trues if _half_of(s) != h]
        if not d_f:
            continue
        dset = d_f + d_t
        d_fset, d_tset = set(d_f), set(d_t)
        scored = []
        for a, ks in atoms_full.items():
            dk = len(ks & d_fset)
            if dk >= 1 and full_touch[a] <= 3 * budget:
                scored.append((a, dk))
        scored.sort(key=lambda x: (-x[1], full_touch[x[0]]))
        keep = [a for a, _ in scored[:150]]
        datoms = {a: atoms_full[a] & set(dset) for a in keep}
        found = {}

        def consider(steps):
            ks = _conjunction_kill(steps, datoms, dset)
            k, t = len(ks & d_fset), len(ks & d_tset)
            if k >= 2:
                key = frozenset(steps)
                if key not in found or t < found[key][1]:
                    found[key] = (k, t)

        for a in keep:
            consider((("is", a),))
        for s1, s2 in itertools.combinations(sorted(found), 2):
            st = tuple(sorted(set(s1) | set(s2)))
            if len(st) == 2:
                consider(st)
        pairs = [k for k in found if len(k) == 2]
        for pr in pairs:
            for a in keep:
                st = tuple(sorted(set(pr) | {("is", a)}))
                if len(st) == 3:
                    consider(st)
        for conj in _gini_paths(datoms, d_fset, d_tset):
            steps = tuple(sorted(set(conj)))
            if 1 <= len(steps) <= 3:
                ks = _conjunction_kill(steps, datoms, dset)
                k, t = len(ks & d_fset), len(ks & d_tset)
                if k >= 2:
                    found[frozenset(steps)] = (k, t)
        for key, (dk, _dt) in found.items():
            steps = tuple(sorted(key))
            eks = _conjunction_kill(steps, atoms_full, e_f + e_t)
            ek, et = len(eks & set(e_f)), len(eks & set(e_t))
            rec = cand.setdefault(
                key,
                {
                    "steps": [list(s) for s in steps],
                    "ho_kills": 0,
                    "ho_touches": 0,
                    "deriv_kills": 0,
                },
            )
            rec["ho_kills"] += ek
            rec["ho_touches"] = max(rec["ho_touches"], et)
            rec["deriv_kills"] = max(rec["deriv_kills"], dk)
    for rec in cand.values():
        steps = tuple(tuple(s) for s in rec["steps"])
        fks = _conjunction_kill(steps, atoms_full, falses + trues)
        rec["full_kills"] = len(fks & target_set)
        rec["full_touches"] = len(fks & tset)
        rec["killed_sids"] = sorted(fks & target_set)
        rec["ho_touches_scaled"] = 2 * rec["ho_touches"]
        rec["supported"] = rec["ho_kills"] >= 2 and rec["ho_touches_scaled"] <= budget
    return cand


def learn_family(feat: dict, falses: list, trues: list, targets, census_residual):
    """One family's shadow entry: certified and failed candidates."""
    budget = max(2, int(round(0.10 * len(trues)))) if trues else 2
    entry = {
        "n_falses": len(falses),
        "n_trues": len(trues),
        "budget": budget,
        "programme_residual": len(targets),
        "census_residual": len(census_residual),
        "supported": [],
        "failed_heldout": [],
        "note": "",
    }
    if not targets or not trues:
        entry["note"] = (
            "no programme-residual falses to target" if not targets else "no true base"
        )
        return entry
    cand = _family_candidates(feat, falses, trues, targets, budget)
    sup = [r for r in cand.values() if r["supported"]]
    sup.sort(key=lambda r: (-r["ho_kills"], r["ho_touches_scaled"]))
    entry["supported"] = sup[:6]
    failed = [
        r
        for r in cand.values()
        if not r["supported"] and r["full_kills"] >= 2 and r["full_touches"] <= budget
    ]
    failed.sort(key=lambda r: (-r["full_kills"], r["full_touches"]))
    entry["failed_heldout"] = failed[:4]
    if not sup:
        entry["note"] = "learner finds nothing beyond the rule prices"
    return entry


def learn_population(rows: list[dict], residuals: dict, pricing: dict) -> dict:
    """The shadow register over a census population and its residuals."""
    famdata = _family_features(rows)
    results = {}
    for fam, d in sorted(famdata.items()):
        falses, trues = d["F"], d["T"]
        fset = set(falses)
        targets = [s for s in residuals.get(fam, []) if s in fset]
        census_residual = pricing.get(fam, {}).get("residual", [])
        results[fam] = learn_family(
            d["feat"], falses, trues, targets, census_residual
        )
    return {
        "population": {
            "rows": len(rows),
            "falses": sum(d["n_falses"] for d in results.values()),
            "trues": sum(d["n_trues"] for d in results.values()),
            "programme_residual_total": sum(
                d["programme_residual"] for d in results.values()
            ),
            "census_residual_total": sum(
                d["census_residual"] for d in results.values()
            ),
        },
        "families": results,
    }


def main(argv: list[str] | None = None) -> int:
    """Run the shadow learner over census artifacts into a register."""
    parser = argparse.ArgumentParser(prog="shadow_learner")
    parser.add_argument("population", type=Path)
    parser.add_argument("residuals", type=Path)
    parser.add_argument("pricing", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args(argv)
    with open(args.population) as fh:
        rows = [json.loads(ln) for ln in fh]
    with open(args.residuals) as fh:
        residuals = parse_residual_lists(fh)
    with open(args.pricing) as fh:
        pricing = json.load(fh)
    register = learn_population(rows, residuals, pricing)
    atomic_write_json(args.out, register, canonical=False, indent=1)
    print(json.dumps(register["population"], indent=1))
    for fam, e in register["families"].items():
        print(
            f"{fam}: F={e['n_falses']} T={e['n_trues']} "
            f"prog_resid={e['programme_residual']} "
            f"census_resid={e['census_residual']} "
            f"supported={len(e['supported'])} "
            f"failed_ho={len(e['failed_heldout'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
