#!/usr/bin/env python3
"""NW-17 Step 19 validation: draft rules over the held-out slice, from cache."""
import hashlib, json, pathlib, re, resource, sys, time
sys.path.insert(0, "/content/nw17")
import importlib.util
spec = importlib.util.spec_from_file_location("census", "/content/nw17/census.py")
census = importlib.util.module_from_spec(spec); spec.loader.exec_module(census)

ROOT = pathlib.Path("/content/nw17")
ORACLE2_EXTRA = {
    "results_announcement": re.compile(r"(?i)\bresults\b"),
    "press_release_residual": None,
}
PERIOD = re.compile(r"(?i)quarter|annual|interim|half|fiscal|financial|operating")

def lines_of(res, cap):
    out = []
    for txt in (res.get("text_primary", ""), res.get("text_exhibit", "")):
        for ln in txt.splitlines():
            ln = ln.strip()
            if ln and len(ln) <= cap: out.append(ln)
    return out

def anchored_lines(res):
    out = []
    for ln in lines_of(res, 100):
        if ln[0].islower(): continue
        if ln.endswith((".", ",", ";")): continue
        out.append(ln)
    return out

def main():
    t0 = time.time()
    held = []
    for d in sorted((ROOT / "cache").iterdir()):
        f = d / "done.json"
        if not f.exists(): continue
        r = json.loads(f.read_text())
        if r.get("error"): continue
        if int(hashlib.md5(r["accession"].encode()).hexdigest()[:8], 16) % 5 >= 2: continue
        held.append(r)
    print("heldout n", len(held), flush=True)
    items = ["financial_statements", "results_announcement", "governance_notice",
             "dividend_capital", "press_release_residual"]
    out = {"n": len(held), "items": {}}
    for key in items:
        rr = census.RULES[key]
        hits, oracle = [], 0
        for r in held:
            hit = next((ln for ln in anchored_lines(r) if rr["strict"].search(ln)), None)
            if hit: hits.append({"accession": r["accession"], "hit": hit})
            o = any(rr["oracle"].search(ln) for ln in lines_of(r, 140))
            if not o and key == "results_announcement":
                o = any(re.search(r"(?i)\bresults\b", ln) and PERIOD.search(ln) for ln in lines_of(r, 140))
            if o: oracle += 1
        out["items"][key] = {"hits": hits, "n_hits": len(hits), "oracle_v2": oracle,
                             "coverage": round(len(hits) / oracle, 3) if oracle else None}
        print(key, len(hits), oracle, out["items"][key]["coverage"], flush=True)
    out["elapsed_s"] = round(time.time() - t0, 1)
    out["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    (ROOT / "validation.json").write_text(json.dumps(out))
    print("done", out["elapsed_s"], out["peak_rss_mb"], flush=True)

if __name__ == "__main__":
    main()
