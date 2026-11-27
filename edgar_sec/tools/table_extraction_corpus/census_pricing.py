"""Imposter-census pricing over the assembled census population.

Per family, derives the feature inventory from its own specimens,
prices candidates singly and in combination as kills/touches, and
names the residual falses surviving the best priced combination.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from edgar_sec.infra.storage.atomic import atomic_write_json

MONTHS = (
    "january february march april may june july august september "
    "october november december jan feb mar apr jun jul aug sep sept "
    "oct nov dec"
).split()
NUM_RE = re.compile(r"\(?-?\$?\s*\d[\d,]*(\.\d+)?\s*\)?%?\)?")
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
DATE_RE = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\s+\d{1,2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b"
)
MOVE_WORDS = {
    "additions",
    "deductions",
    "increases",
    "decreases",
    "amortization",
    "depreciation",
    "payments",
    "proceeds",
    "purchases",
    "sales",
    "transfers",
    "charges",
    "activity",
    "acquisitions",
    "dispositions",
    "contributions",
    "distributions",
    "settlements",
    "forfeitures",
    "exercises",
    "exercised",
    "grants",
    "granted",
    "issued",
    "issuance",
    "redemptions",
    "repurchases",
    "impairment",
    "accretion",
    "changes",
    "change",
    "adjustments",
    "remeasurement",
    "benefits",
    "service",
    "cost",
    "expense",
    "income",
}


def norm(s: str) -> str:
    """Lowercase a text fragment and collapse non-alphanumerics."""
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def stub_key(stub: str) -> str:
    """A stub's vocabulary key: numbers and months removed."""
    s = norm(stub)
    s = re.sub(r"\b\d+\b", " ", s)
    toks = [t for t in s.split() if t not in MONTHS and len(t) > 1]
    return " ".join(toks[:8])


def cells_of(line: str) -> list[str]:
    """Split one rendered table line into its cells."""
    return [c.strip() for c in line.split("|")]


def specimen_features(row: dict) -> dict:
    """The feature inventory of one census specimen."""
    lines = [ln for ln in row["table_text"].split("\n") if ln.strip()]
    stubs, headers = [], []
    n_cols = 0
    num_cells = tot_cells = pct_cells = 0
    for i, ln in enumerate(lines):
        cells = cells_of(ln)
        n_cols = max(n_cols, len(cells))
        stub = cells[0] if cells else ""
        if stub:
            stubs.append(stub)
        if i < 3:
            headers.extend(c for c in cells if c)
        for c in cells:
            if c:
                tot_cells += 1
                if NUM_RE.fullmatch(c.replace("$", "").strip()) or (
                    re.search(r"\d", c) and NUM_RE.search(c)
                ):
                    num_cells += 1
                if "%" in c:
                    pct_cells += 1
    f = {}
    skeys = [stub_key(s) for s in stubs]
    skeys = [k for k in skeys if len(k) >= 3]
    for k in set(skeys):
        f[f"stub:{k}"] = 1
    stop = {
        "and",
        "the",
        "for",
        "of",
        "in",
        "on",
        "at",
        "to",
        "a",
        "an",
        "dollars",
        "thousands",
        "millions",
        "billions",
        "unaudited",
        "audited",
        "per",
        "share",
        "shares",
    }
    hkeys = set()
    for h in headers:
        hk = stub_key(h)
        if len(hk) >= 3:
            hkeys.add(hk)
        for tok in norm(h).split():
            if len(tok) > 2 and not tok.isdigit() and tok not in stop:
                hkeys.add(tok)
    for k in hkeys:
        f[f"hdr:{k}"] = 1
    cap_toks = set()
    for cap in row["caption_stack"]:
        cap_toks.update(t for t in norm(cap).split() if len(t) > 2 and t not in stop)
    for t in cap_toks:
        f[f"cap:{t}"] = 1
    prose = norm(row["prose_before"][-700:] + " " + row["prose_after"][:300])
    for t in set(prose.split()):
        if len(t) > 3:
            f[f"prose:{t}"] = 1
    n_rows = len(lines)
    f["n_rows"] = n_rows
    f["n_cols"] = n_cols
    num_share = (num_cells / tot_cells) if tot_cells else 0.0
    pct_share = (pct_cells / tot_cells) if tot_cells else 0.0
    f["num_share"] = round(num_share, 3)
    f["pct_share"] = round(pct_share, 3)
    stub_blob = " ".join(norm(s) for s in stubs)
    f["has_total_row"] = int(
        any(
            t == "total" or t.startswith("total ") or t.endswith(" total")
            for t in (norm(s) for s in stubs)
        )
    )
    f["bookend_begin"] = int(
        bool(
            re.search(
                r"beginning|opening balance|balance at (the )?beginning",
                stub_blob,
            )
        )
    )
    f["bookend_end"] = int(
        bool(re.search(r"ending|closing balance|balance at (the )?end", stub_blob))
    )
    f["has_bookend_pair"] = f["bookend_begin"] and f["bookend_end"]
    move_hits = sum(1 for s in stubs if MOVE_WORDS & set(norm(s).split()))
    f["move_density"] = round(move_hits / max(1, len(stubs)), 3)
    head_blob = " ".join(headers)
    f["date_header"] = int(bool(DATE_RE.search(head_blob.lower())))
    f["year_ladder"] = int(len(re.findall(r"\b(?:19|20)\d{2}\b", head_blob)) >= 3)
    f["asof_header"] = int("as of" in head_blob.lower())
    f["_stub_keys"] = skeys
    f["_stub_blob"] = stub_blob
    return f


def price_rule(kill_set_f: set, kill_set_t: set, sparse_t: set) -> dict:
    """One candidate's price: kills, touches, touches on sparse trues."""
    return {
        "kills": len(kill_set_f),
        "touches": len(kill_set_t),
        "touches_sparse": len(kill_set_t & sparse_t),
    }


def _run_greedy(cand_pool: dict, cand: dict, select_f: set) -> tuple:
    killed_f, killed_t, legs = set(), set(), []
    avail = dict(cand_pool)
    for _ in range(6):
        best = None
        for name, (kf, kt) in avail.items():
            add_k = len((kf & select_f) - killed_f)
            add_t = len(kt - killed_t)
            if add_k >= 1 and add_t <= 1:
                score = (add_k, -add_t)
                if best is None or score > best[0]:
                    best = (score, name, kf, kt)
        if best is None:
            break
        _score, name, kf, kt = best
        legs.append(name)
        killed_f |= kf & select_f
        killed_t |= kt
        del avail[name]
    return legs, killed_t


def _family_register(fam_rows: dict, feat: dict, sparse: set) -> dict:
    f_sids, t_sids = fam_rows["_F"], fam_rows["_T"]
    if not f_sids:
        return {
            "n_falses": 0,
            "n_trues": len(t_sids),
            "n_sparse_trues": len(sparse),
            "core_vocab": fam_rows["core_vocab"],
            "singles": [],
            "zero_price_candidates": 0,
            "combos": {},
            "residual": [],
            "note": "no falses on this population",
        }
    # feature universe (binary features only)
    universe = Counter()
    for sid in f_sids + t_sids:
        for k, v in feat[sid].items():
            if k.startswith("_") or k in (
                "n_rows",
                "n_cols",
                "num_share",
                "pct_share",
                "move_density",
            ):
                continue
            if v:
                universe[k] += 1

    # structural threshold features
    def add_struct(name, fn):
        for sid in f_sids + t_sids:
            if fn(feat[sid]):
                feat[sid][name] = 1
                universe[name] += 1

    for k in (3, 5, 8, 12):
        add_struct(f"rows_le_{k}", lambda f, k=k: f["n_rows"] <= k)
    for t in (0.3, 0.5, 0.7):
        add_struct(f"numshare_ge_{t}", lambda f, t=t: f["num_share"] >= t)
        add_struct(f"pctshare_ge_{t}", lambda f, t=t: f["pct_share"] >= t)
    for t in (0.25, 0.5):
        add_struct(f"movedens_le_{t}", lambda f, t=t: f["move_density"] <= t)

    singles = []
    cand = {}  # name -> (killF set, killT set)
    for name in universe:
        ff = {s for s in f_sids if feat[s].get(name)}
        ft = {s for s in t_sids if feat[s].get(name)}
        # direction A: kill if present
        if len(ff) >= 1:
            singles.append(
                {
                    "feature": name,
                    "dir": "A_present",
                    **price_rule(ff, ft, sparse),
                }
            )
            cand[f"A:{name}"] = (ff, ft)
        # direction B: kill if absent (only features trues carry)
        if t_sids and len(ft) >= 0.5 * len(t_sids):
            kf = set(f_sids) - ff
            kt = set(t_sids) - ft
            singles.append(
                {
                    "feature": name,
                    "dir": "B_absent",
                    **price_rule(kf, kt, sparse),
                }
            )
            cand[f"B:{name}"] = (kf, kt)
    singles.sort(key=lambda s: (-s["kills"], s["touches"]))
    zero_price = [s for s in singles if s["kills"] == 0]

    # Combination pool: recurring content legs only (stub/header/
    # caption/host/structural); prose tokens price as singles but
    # cannot serve as legs — a lexical pool memorizes the set.
    content_prefixes = ("stub:", "hdr:", "cap:", "host:", "host1:")
    structural = (
        "rows_le_",
        "numshare_ge_",
        "pctshare_ge_",
        "movedens_le_",
        "has_total_row",
        "bookend_begin",
        "bookend_end",
        "has_bookend_pair",
        "date_header",
        "year_ladder",
        "asof_header",
    )
    max_leg_touches = max(2, int(0.10 * len(t_sids)))

    def in_pool(key):
        name = key[2:]
        if not (name.startswith(content_prefixes) or name.startswith(structural)):
            return False
        kf, kt = cand[key]
        return len(kf) >= 2 and len(kt) <= max_leg_touches

    pool = {k: v for k, v in cand.items() if in_pool(k)}

    # core-absence conjunctions (Step 9 uniform-language form),
    # over the strong core (>=50% of trues) and the full derived
    # core vocabulary (>=20%)
    combos = {}
    strong_terms = fam_rows["_core_strong"]
    vocab_terms = sorted(fam_rows["core_vocab"])

    def core_cells(terms, tag):
        if not terms:
            return
        kf = {s for s in f_sids if any(not feat[s].get(f"stub:{t}") for t in terms)}
        kt = {s for s in t_sids if any(not feat[s].get(f"stub:{t}") for t in terms)}
        combos[f"core_absence_any_{tag}"] = {
            "legs": [f"B:stub:{t}" for t in terms],
            **price_rule(kf, kt, sparse),
        }
        for share in (0.5, 0.75):
            need = share * len(terms)
            kf = {
                s
                for s in f_sids
                if sum(1 for t in terms if feat[s].get(f"stub:{t}")) < need
            }
            kt = {
                s
                for s in t_sids
                if sum(1 for t in terms if feat[s].get(f"stub:{t}")) < need
            }
            combos[f"core_share_lt_{share}_{tag}"] = {
                "legs": [f"core_share<{share} of {tag}"],
                **price_rule(kf, kt, sparse),
            }

    core_cells(strong_terms, "strong")
    core_cells(vocab_terms, "vocab")

    legs, _kt = _run_greedy(pool, cand, set(f_sids))
    killed_f = set()
    killed_t = set()
    for leg in legs:
        killed_f |= cand[leg][0]
        killed_t |= cand[leg][1]
    combos["greedy"] = {
        "legs": legs,
        **price_rule(killed_f, killed_t, sparse),
    }
    # held-out cross-pricing: derive the greedy combination on one
    # half of the falses, price its kills on the other half (and
    # vice versa). A combination that only memorizes collapses here.
    half = {s: int(hashlib.sha1(s.encode()).hexdigest()[:8], 16) % 2 for s in f_sids}
    cross_kills = 0
    cross_touches = 0
    for h in (0, 1):
        sel = {s for s in f_sids if half[s] == h}
        ev = set(f_sids) - sel
        if not sel or not ev:
            continue
        hlegs, _ = _run_greedy(pool, cand, sel)
        hkf, hkt = set(), set()
        for leg in hlegs:
            hkf |= cand[leg][0]
            hkt |= cand[leg][1]
        cross_kills += len(hkf & ev)
        cross_touches = max(cross_touches, len(hkt))
    combos["heldout_greedy"] = {
        "legs": ["greedy derived per half, content pool"],
        "kills": cross_kills,
        "touches": cross_touches,
        "touches_sparse": 0,
        "of_falses": len(f_sids),
    }
    # pairwise over top-8 pool singles
    top = []
    seen = set()
    for s in singles:
        key = ("A:" if s["dir"] == "A_present" else "B:") + s["feature"]
        if key in pool and key not in seen:
            top.append(key)
            seen.add(key)
        if len(top) >= 8:
            break
    best_pair = None
    for i in range(len(top)):
        for j in range(i + 1, len(top)):
            kf = cand[top[i]][0] | cand[top[j]][0]
            kt = cand[top[i]][1] | cand[top[j]][1]
            cell = {
                "legs": [top[i], top[j]],
                **price_rule(kf, kt, sparse),
            }
            if best_pair is None or (cell["kills"], -cell["touches"]) > (
                best_pair["kills"],
                -best_pair["touches"],
            ):
                best_pair = cell
    if best_pair:
        combos["best_pair"] = best_pair
    # Separation standard: a combination separates only within the
    # leg budget applied to whole combinations; over-budget cells
    # are priced findings, never separators. Best = max kills in budget.
    budget = max(2, int(round(0.10 * len(t_sids))))
    eligible = {
        k: v
        for k, v in combos.items()
        if k != "heldout_greedy" and v["touches"] <= budget
    }
    best_over_budget = False
    if eligible:
        best = None
        for cname, cell in eligible.items():
            key = (cell["kills"], -cell["touches"])
            if best is None or key > best[0]:
                best = (key, cname, cell)
    else:
        best_over_budget = True
        best = None
        for cname, cell in combos.items():
            if cname == "heldout_greedy":
                continue
            key = (-cell["touches"], cell["kills"])
            if best is None or key > best[0]:
                best = (key, cname, cell)
    best_name, best_cell = best[1], best[2]
    bkf = set()
    if best_name in ("greedy", "best_pair"):
        for leg in best_cell["legs"]:
            bkf |= cand[leg][0]
    elif best_name.startswith("core_absence_any"):
        terms = strong_terms if best_name.endswith("_strong") else vocab_terms
        bkf = {s for s in f_sids if any(not feat[s].get(f"stub:{t}") for t in terms)}
    elif best_name.startswith("core_share"):
        parts = best_name.split("_")
        share = float(parts[3])
        terms = strong_terms if parts[4] == "strong" else vocab_terms
        need = share * len(terms)
        bkf = {
            s
            for s in f_sids
            if sum(1 for t in terms if feat[s].get(f"stub:{t}")) < need
        }
    lexical = {key: v for key, v in cand.items() if key not in pool}
    residual = []
    for sid in f_sids:
        if sid not in bkf:
            r = fam_rows["_rows"][sid]
            residual.append(
                {
                    "sid": sid,
                    "final_class": r.get("final_class"),
                    "mechanism": r.get("mechanism"),
                    "true_family": r.get("true_family"),
                    "firm": sid.split("-")[0],
                    "core_terms_carried": sorted(
                        t for t in strong_terms if feat[sid].get(f"stub:{t}")
                    ),
                    "killed_by_lexical_single": any(
                        sid in kf and len(kt) <= 2 for kf, kt in lexical.values()
                    ),
                }
            )
    return {
        "n_falses": len(f_sids),
        "n_trues": len(t_sids),
        "n_sparse_trues": len(sparse),
        "core_vocab": fam_rows["core_vocab"],
        "singles": singles[:40],
        "singles_total": len(singles),
        "pool_legs": len(pool),
        "zero_price_candidates": len(zero_price),
        "zero_price_examples": [s["feature"] + "|" + s["dir"] for s in zero_price[:10]],
        "combos": combos,
        "best_combo": best_name,
        "touch_budget": budget,
        "best_over_budget": best_over_budget,
        "singles_inbudget": [s for s in singles if s["touches"] <= budget][:20],
        "residual": residual,
    }


def price_population(rows: list[dict]) -> dict:
    """The census pricing register over assembled population rows."""
    fams = defaultdict(lambda: {"false": [], "true": []})
    for r in rows:
        if r["text_source"] is None:
            continue
        side = "false" if r["side"] == "false" else "true"
        fams[r["family"]][side].append(r)

    staged = {}
    for fam in sorted(fams):
        falses = fams[fam]["false"]
        trues = fams[fam]["true"]
        if not falses and not trues:
            continue
        feat = {}
        for r in falses + trues:
            feat[r["sid"]] = specimen_features(r)
        # sparse trues: bottom quartile by n_rows
        t_sorted = sorted(trues, key=lambda r: feat[r["sid"]]["n_rows"])
        n_sparse = max(1, len(trues) // 4) if trues else 0
        sparse_ids = {r["sid"] for r in t_sorted[:n_sparse]}
        # core vocabulary from trues' stub keys
        tcount = Counter()
        for r in trues:
            for k in set(feat[r["sid"]]["_stub_keys"]):
                tcount[k] += 1
        n_t = max(1, len(trues))
        core = {k: c for k, c in tcount.items() if c >= max(2, 0.2 * n_t)}
        core_strong = {k for k, c in core.items() if c >= 0.5 * n_t}
        staged[fam] = {
            "n_falses": len(falses),
            "n_trues": len(trues),
            "n_sparse_trues": len(sparse_ids),
            "core_vocab": {
                k: round(c / n_t, 3)
                for k, c in sorted(core.items(), key=lambda kv: -kv[1])
            },
            "_feat": feat,
            "_sparse": sparse_ids,
            "_F": [r["sid"] for r in falses],
            "_T": [r["sid"] for r in trues],
            "_core_strong": sorted(core_strong),
            "_rows": {r["sid"]: r for r in falses + trues},
        }

    # host features: presence of another family's strong core terms
    strong = {fam: set(d["_core_strong"]) for fam, d in staged.items()}
    for fam, d in staged.items():
        for sid, f in d["_feat"].items():
            keys = set(f["_stub_keys"])
            for other, vocab in strong.items():
                if other != fam and vocab:
                    inter = len(keys & vocab)
                    if inter >= 2:
                        f[f"host:{other}"] = 1
                    if inter >= 1:
                        f[f"host1:{other}"] = 1

    register = {}
    for fam, d in staged.items():
        register[fam] = _family_register(d, d["_feat"], d["_sparse"])
    return register


def main(argv: list[str] | None = None) -> int:
    """Price a census population file into a pricing register file."""
    parser = argparse.ArgumentParser(prog="census_pricing")
    parser.add_argument("population", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args(argv)
    with open(args.population) as fh:
        rows = [json.loads(ln) for ln in fh]
    register = price_population(rows)
    atomic_write_json(args.out, register, canonical=False, indent=1)
    print(
        json.dumps(
            {
                fam: {
                    "F": d["n_falses"],
                    "T": d["n_trues"],
                    "resid": len(d["residual"]),
                }
                for fam, d in register.items()
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
