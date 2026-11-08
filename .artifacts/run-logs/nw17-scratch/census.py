#!/usr/bin/env python3
"""NW-17 Step 18: 6-K corpus census, on-session (Colab High-RAM, 8 workers).

Phase A: stream submissions.zip members -> 6-K/6-K/A slice + population counts.
Phase B: fetch the stratified draw (index.htm, primary, up to 3 exhibits),
         normalize to text, measure candidate structures.
Phase C: aggregate -> out.json (draft vs held-out split by md5(accession)).
"""
import hashlib, io, json, os, re, resource, sys, time, urllib.request, zipfile
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path("/content/nw17"); ROOT.mkdir(parents=True, exist_ok=True)
CACHE = ROOT / "cache"; CACHE.mkdir(exist_ok=True)
UA = os.environ.get("SEC_USER_AGENT", "edgar-sec-nw17-census/1.0 admin@sample.com")
WORKERS = 8
ERAS = [("pre-2001", 0, 2000), ("2001-2005", 2001, 2005), ("2006-2010", 2006, 2010),
        ("2011-2015", 2011, 2015), ("2016-2020", 2016, 2020), ("2021-2026", 2021, 9999)]

def era_of(date):
    y = int((date or "0")[:4] or 0)
    for name, lo, hi in ERAS:
        if lo <= y <= hi: return name
    return "pre-2001"

import threading
_gate = threading.Lock(); _last = [0.0]
def _throttle():
    with _gate:
        now = time.monotonic(); wait = _last[0] + 0.22 - now
        if wait > 0: time.sleep(wait)
        _last[0] = time.monotonic()

def fetch(url, binary=False, timeout=30):
    for attempt, backoff in enumerate((0, 20, 45, 90)):
        if backoff: time.sleep(backoff)
        _throttle()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            if data[:2] == b"\x1f\x8b":
                import gzip as _gz; data = _gz.decompress(data)
            return data if binary else data.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 3: continue
            raise
    raise RuntimeError("unreachable")
# ---------------- Phase A ----------------
def phase_a():
    zpath = ROOT / "submissions.zip"
    if not zpath.exists():
        print("downloading submissions.zip ...", flush=True)
        req = urllib.request.Request("https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=600) as r, open(zpath, "wb") as f:
            while chunk := r.read(1 << 20): f.write(chunk)
    print("zip bytes", zpath.stat().st_size, flush=True)
    rows = []
    with zipfile.ZipFile(zpath) as z:
        names = [n for n in z.namelist() if n.startswith("CIK") and n.endswith(".json")]
        print("members", len(names), flush=True)
        for n in names:
            try: doc = json.loads(z.read(n))
            except Exception: continue
            cik = str(doc.get("cik", "")).zfill(10)
            rec = doc.get("filings", {}).get("recent", {}) or {}
            hist = doc.get("filings", {}).get("files", []) or []
            def take(rec):
                m = min(len(rec.get("accessionNumber", [])), len(rec.get("form", [])))
                for i in range(m):
                    form = rec["form"][i]
                    if form in ("6-K", "6-K/A"):
                        rows.append((cik, rec["accessionNumber"][i], form, rec["filingDate"][i],
                                     rec["primaryDocument"][i] if i < len(rec.get("primaryDocument", [])) else "",
                                     bool(rec["isXBRL"][i]) if i < len(rec.get("isXBRL", [])) else False,
                                     bool(rec["isInlineXBRL"][i]) if i < len(rec.get("isInlineXBRL", [])) else False))
            take(rec)
            for h in hist:
                try:
                    sub = json.loads(z.read(h["name"]))
                    take(sub)
                except Exception: continue
    # dedupe by accession
    seen = {}
    for r in rows: seen[r[1]] = r
    rows = sorted(seen.values(), key=lambda r: (r[3], r[1]))
    (ROOT / "slice.json").write_text(json.dumps(rows))
    from collections import Counter
    pop = Counter((r[2], era_of(r[3])) for r in rows)
    print("slice rows", len(rows), dict(pop), flush=True)
    return rows

def draw(rows):
    from collections import defaultdict
    cells = defaultdict(list)
    for r in rows: cells[(r[2], era_of(r[3]))].append(r)
    out = []
    for (form, era), lst in sorted(cells.items()):
        lst.sort(key=lambda r: hashlib.md5(r[1].encode()).hexdigest())
        k = 70 if form == "6-K" else 15
        out.extend(lst[:k])
    return out

# ---------------- Phase B ----------------
class TextExtract(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []; self.skip = 0
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"): self.skip += 1
        if tag in ("p", "div", "tr", "br", "h1", "h2", "h3", "h4", "li", "table"):
            self.parts.append("\n")
    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip: self.skip -= 1
        if tag in ("p", "div", "tr", "table"): self.parts.append("\n")
    def handle_data(self, d):
        if not self.skip: self.parts.append(d)

def to_text(raw, name):
    if name.lower().endswith((".htm", ".html")) or raw[:200].lower().find(b"<html") >= 0 or b"<table" in raw[:2000].lower():
        p = TextExtract()
        try: p.feed(raw.decode("utf-8", "replace"))
        except Exception: pass
        txt = "".join(p.parts)
    else:
        txt = raw.decode("utf-8", "replace")
    lines = [re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in txt.splitlines()]
    return "\n".join(ln for ln in lines if ln)

EX99_RE = re.compile(r"ex[-_]?99|exhibit[-_]?99|exh[-_]?99|exv99w", re.I)
def measure_one(row):
    cik, acc, form, date, primary, xbrl, ixbrl = row
    nodash = acc.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{nodash}"
    cdir = CACHE / acc; cdir.mkdir(exist_ok=True)
    done = cdir / "done.json"
    if done.exists():
        return json.loads(done.read_text())
    res = {"cik": cik, "accession": acc, "form": form, "date": date, "era": era_of(date),
           "split": "heldout" if int(hashlib.md5(acc.encode()).hexdigest()[:8], 16) % 5 < 2 else "draft",
           "error": None, "exhibits": [], "primary_type": None}
    try:
        htm = fetch(f"{base}/{acc}-index.htm")
        # typed rows: Document | Type | Description
        typed = re.findall(r"<tr[^>]*>(.*?)</tr>", htm, re.S | re.I)
        docs = []
        for tr in typed:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)
            if len(cells) >= 5:
                link = re.search(r'href="([^"]+)"', cells[2])
                name = re.sub(r"<[^>]+>", "", cells[2]).strip()
                typ = re.sub(r"<[^>]+>", "", cells[3]).strip().upper()
                if link and name and not name.lower().endswith((".jpg", ".gif", ".png")):
                    docs.append((name, typ))
        res["docs"] = docs
        ex99 = [d for d in docs if d[1].startswith("EX-99")]
        res["exhibit_types"] = sorted({d[1] for d in docs if d[1].startswith("EX-")})
        res["n_ex99"] = len(ex99)
        targets = []
        prim = [d for d in docs if d[0] == primary] or docs[:1]
        if prim: targets.append((prim[0][0], prim[0][1], "primary"))
        for name, typ in ex99[:3]: targets.append((name, typ, "exhibit"))
        texts = {}
        for name, typ, role in targets:
            try:
                raw = fetch(f"{base}/{name}", binary=True)
                if len(raw) > 9_000_000: continue
                texts[role] = texts.get(role, "") + "\n" + to_text(raw, name)
                if role == "exhibit": res["exhibits"].append(typ)
            except Exception as e:
                res.setdefault("fetch_errors", []).append(f"{name}:{type(e).__name__}")
            time.sleep(0.12)
        res["text_primary"] = texts.get("primary", "")[:200000]
        res["text_exhibit"] = texts.get("exhibit", "")[:300000]
    except Exception as e:
        res["error"] = f"{type(e).__name__}: {e}"
    if not res["error"]:
        done.write_text(json.dumps(res))
    return res

# Candidate rules: strict = heading-line pattern; oracle = loose anywhere pattern.
RULES = {
 "financial_statements": {
   "strict": re.compile(r"(?i)^(consolidated |group |company )?(income statement|statement of (profit or loss|comprehensive income|financial position|operations)|balance sheet)\b|^\((loss)\)/profit for the (year|period)\b|^\(loss\)/profit per share\b"),
   "oracle": re.compile(r"(?i)statement of financial position|income statement|profit or loss|balance sheet|cash flow statement")},
 "results_announcement": {
   "strict": re.compile(r"(?i)(results announcement|announces? .{0,40}results|financial results for|earnings announcement|interim results|annual results|half[- ]year(ly)? results|quarterly results|preliminary results)"),
   "oracle": re.compile(r"(?i)\bresults\b.{0,60}\b(revenue|net income|profit|loss per share|eps)\b|announces? .{0,40}results")},
 "production_operating": {
   "strict": re.compile(r"(?i)(production report|operating update|operations update|production and sales report|quarterly activities report|exploration (and )?production|drilling report)"),
   "oracle": re.compile(r"(?i)\bproduction\b.{0,50}\b(barrels|boe|tonnes|tons|ounces|output)\b|operating update|production report")},
 "governance_notice": {
   "strict": re.compile(r"(?i)(notice of (the )?(annual |extraordinary )?general meeting|annual general meeting|extraordinary general meeting|changes? in (the )?board|appointment of .{0,30}director|director resignation|resignation of .{0,30}director)"),
   "oracle": re.compile(r"(?i)general meeting|board of directors.{0,60}(appoint|resign|elect)|appointed as (a )?director")},
 "dividend_capital": {
   "strict": re.compile(r"(?i)(dividend (declaration|announcement|payment)|declares? .{0,30}dividend|share repurchase|share buy[- ]back|buyback program|capital return)"),
   "oracle": re.compile(r"(?i)\bdividend\b|share repurchase|buy[- ]back")},
 "material_event": {
   "strict": re.compile(r"(?i)(material definitive agreement|entry into a material|credit agreement|underwriting agreement|completion of (the )?acquisition|merger agreement|indenture)"),
   "oracle": re.compile(r"(?i)material agreement|credit agreement|merger|acquisition of|underwriting")},
 "report_furnished": {
   "strict": re.compile(r"(?i)^(interim report|semi-annual report|half[- ]year report|annual report)\b|furnishes? .{0,40}(interim|annual|half-year) report"),
   "oracle": re.compile(r"(?i)interim report|semi-annual|half-year report|annual report for the (year|fiscal)")},
 "press_release_residual": {
   "strict": re.compile(r"(?i)^press release\b|for immediate release"),
   "oracle": re.compile(r"(?i)press release|for immediate release")},
}
COVER = {
 "fpi_title": re.compile(r"(?i)report of foreign private issuer pursuant to rule 13a-16 or 15d-16"),
 "month_of": re.compile(r"(?i)for the month of"),
 "annual_cover_20f_40f": re.compile(r"(?i)annual reports? under cover of form (20-f|40-f)"),
 "signatures": re.compile(r"(?i)^signatures?$|^pursuant to the requirements"),
 "exhibit_index_ref": re.compile(r"(?i)exhibit (99\.\d|index)"),
}

def apply_rules(res):
    heads_p = [ln for ln in res.get("text_primary", "").splitlines() if len(ln) <= 140]
    heads_e = [ln for ln in res.get("text_exhibit", "").splitlines() if len(ln) <= 140]
    all_lines = heads_p + heads_e
    full = (res.get("text_primary", "") + "\n" + res.get("text_exhibit", ""))
    out = {}
    for key, rr in RULES.items():
        strict_hit = next((ln for ln in all_lines if rr["strict"].search(ln)), None)
        out[key] = {"strict": bool(strict_hit), "hit": strict_hit,
                    "oracle": bool(rr["oracle"].search(full))}
    res["rules"] = out
    head_p = res.get("text_primary", "")[:3000]
    res["cover"] = {k: bool(v.search(head_p)) for k, v in COVER.items()}
    res["headings_sample"] = all_lines[:40]
    return res

def main():
    t0 = time.time()
    rows = phase_a() if not (ROOT / "slice.json").exists() else json.loads((ROOT / "slice.json").read_text())
    if not (ROOT / "slice.json").exists(): pass
    sel = draw([tuple(r) for r in rows])
    (ROOT / "draw.json").write_text(json.dumps(sel))
    print("draw", len(sel), flush=True)
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        results = list(ex.map(measure_one, sel))
    results = [apply_rules(r) for r in results]
    agg = {"workers": WORKERS, "elapsed_s": round(time.time() - t0, 1),
           "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
           "n_draw": len(sel), "n_ok": sum(1 for r in results if not r["error"]),
           "results": results}
    (ROOT / "out.json").write_text(json.dumps(agg))
    print("done", agg["n_ok"], "peakRSS", agg["peak_rss_mb"], flush=True)

if __name__ == "__main__":
    main()
