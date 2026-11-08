# 6-K corpus census and taxonomy draft — Step 18 (item 17)

Run 2026-11-08 on Colab High-RAM (session ruby-anchor-64, caller
secforms:nw17), 8 workers, per-process peak RSS 422.8 MB, census phase
elapsed 292 s. Local work was authoring and this record only; a local
DuckDB slice extraction was OOM-killed on the shared local box and is
not census evidence.

## Findings

1. **Branch taken: exhibit-anchored taxonomy.** Of 510 drawn filings,
   205 (40%) carry at least one exhibit and 187 (37%) carry an EX-99.x;
   the measured structures live in exhibits and in press-release-style
   heading lines, and no drawn filing's heading sample carries an
   8-K-style ITEM-numbered heading. The 6-K body is a short cover
   (61% state "for the month of") plus exhibit references. Step 19
   therefore validates an exhibit-anchored draft (items name exhibit /
   heading classes), not body sections.
2. **Five candidate items clear the census population bar** (draft-slice
   heading-anchored count >= 15 and >= 4% of the draft slice):
   press release, financial statements (IFRS vocabulary), results
   announcement, governance notice, dividend / capital return.
   Three measured candidates fail the bar and are not drafted:
   production / operating report (2), material-event agreements (7),
   furnished interim / annual report (4).
3. **The IFRS label gap from the earnings corpus record is confirmed at
   census scale.** The financial-statements structure is present in
   26% of the draft slice under a loose line-level oracle (82/311) and
   9% under the heading-anchored draft rule (28/311), under headings
   like "Consolidated Statement of Operations and Retained Earnings
   (Deficit)", "INCOME STATEMENT", "Consolidated Balance Sheet" —
   vocabulary the shared 8-K item set cannot name.
4. **6-K/A is a mirror, not a shape.** Amendments are 7,244 of 589,435
   baseline filings (1.2%); the 90 drawn amendments show the same
   heading classes as base 6-K and no amendment-specific structure.
   No separate amendment item is drafted.

## Population frame and reproducibility

Baseline catalog of record (snapshot 08dca382424ef694, the
2026-11-06 bulk-baseline census parquets): **6-K 582,191 filings;
6-K/A 7,244**. The on-session draw frame was built by streaming the
live submissions bulk ZIP (1,573,588,144 bytes, 997,523 members,
downloaded on-session) and unnesting every member's recent + historical
filings, filtered to form in (6-K, 6-K/A), deduplicated by accession:
**6-K 573,807; 6-K/A 7,153; total 580,960** — 1.44% below the baseline
frame, a vintage difference between the 2026-11-07 baseline snapshot
and the live ZIP plus historical-shard coverage; the baseline counts
above are the population of record and the ZIP slice is the draw frame.
Stated query (baseline): unnest `filings` over the snapshot parts,
`form IN ('6-K','6-K/A')`, group by form and era — the same shape the
2026-11-06 bulk-baseline drive ran.

Draw: within each form x era cell (eras pre-2001, 2001-2005,
2006-2010, 2011-2015, 2016-2020, 2021-2026), sort by md5(accession)
and take 70 (6-K) / 15 (6-K/A) — 510 filings. Draft / held-out split
is deterministic and was fixed before drafting: md5(accession) mod 5
< 2 is held-out (199 filings), else draft (311). For each filing the
drive fetched the typed filing index, the primary document, and up to
3 EX-99 exhibits (9 MB cap, images excluded), normalized HTML to text,
and measured the patterns below. Final run: **510/510 filings measured,
zero filing errors** (18 single-exhibit fetch errors, 4 invalid-URL
exhibits, all accounted). Two earlier runs are not evidence: run 1
hit SEC 429s (no global throttle) and run 2 parsed gzip-encoded pages
as text (a fetch-layer defect, since fixed); run 3 added a 5 rps
global throttle with 429 backoff and gzip handling.

## Exhibit composition (510 drawn filings)

| Measure | Count | Share |
|---|---|---|
| At least one exhibit of any EX- type | 205 | 40% |
| EX-99.1 present | 165 | 32% |
| EX-99.2 present | 41 | 8% |
| EX-99.3 present | 24 | 5% |
| EX-99 / EX-99.4 / EX-99.5 present | 17 / 15 / 7 | 3% / 3% / 1% |
| No EX-99 exhibit (0) | 323 | 63% |
| Exactly 1 / 2 / 3+ EX-99 exhibits | 138 / 24 / 25 | 27% / 5% / 5% |
| No exhibits at all | 305 | 60% |

EX-99 presence by era (n / with EX-99): pre-2001 85/10, 2001-2005
85/17, 2006-2010 85/29, 2011-2015 85/42, 2016-2020 85/40,
2021-2026 85/49 — exhibits are a growing, modern-era carrier.

Cover-form patterns (primary document, first 3,000 chars unless
noted): "for the month of" 309/510 (61%); "annual reports under cover
of Form 20-F or Form 40-F" 193 (38%); exhibit-index reference 136
(27%); the full FPI title phrase 61 (12% — the title is line-split in
most covers; the phrase's fragments are among the most frequent
heading lines corpus-wide). These are cover vocabulary, already
served by the existing 6-K cover profile and checkbox schema; they
are not taxonomy items.

## Candidate structures (draft slice, n=311)

Counts: *line* = pattern on any line of <= 140 chars (upper-bound
proxy); *anchored* = the draft rule below; *oracle* = loose pattern
anywhere in the filing text.

| Candidate | Line | Anchored | Oracle | Verdict |
|---|---|---|---|---|
| Press release exhibit | 68 | 55 | 149 | drafted |
| Financial statements (IFRS) | 37 | 28 | 82 | drafted |
| Results announcement | 34 | 21 | 23 | drafted |
| Governance notice | 30 | 19 | 48 | drafted |
| Dividend / capital return | 25 | 15 | 62 | drafted |
| Material-event agreement | 11 | 7 | 80 | below bar — not drafted |
| Furnished report | 8 | 4 | 17 | below bar — not drafted |
| Production / operating report | 3 | 2 | 15 | below bar — not drafted |

Exemplars (accession — matched heading):
- Financial statements: 0001558370-19-000829 (corpus record specimen,
  "Consolidated Income Statement", 83 tables);
  0000945234-04-000285 — "Consolidated Statement of Operations and
  Retained Earnings (Deficit)"; 0001130319-07-000720 — "INCOME
  STATEMENT"; 0001137171-07-001183 — "Consolidated Balance Sheet".
- Results announcement: 0001137171-07-001183 — "SUMMARY OF QUARTERLY
  RESULTS"; 0001279569-10-000901 — "Quarterly results Year to date";
  0000950123-10-097728 — "Interim results for".
- Governance notice: 0001205059-03-000022 — "Notice of Annual and
  Extraordinary General Meeting"; 0001205613-09-000011 — "Sasol
  Limited - Appointment of Director"; 0001193125-07-097161 —
  "APPOINTMENT OF DIRECTORS, SYNDICS, EXTERNAL".
- Dividend / capital return: 0001191638-04-001155 — "DIVIDEND
  DECLARATION"; 0001171843-17-003785 — "Himax Technologies, Inc.
  Declares Cash Dividend for FY2016"; 0001193125-18-319199 — "Share
  repurchase program".
- Press release exhibit: 0000912282-05-000713 — "For Immediate
  Release"; 0001062993-03-000573 — "Press Release dated March 10,
  2003"; 0000899797-02-000224 — "Press Release".

## Draft taxonomy (for Step 19)

Detection rule form (all items): a **heading-anchored** match over
the normalized text the profiles produce — a line of <= 100 chars,
not starting lowercase, not ending in `.` `,` or `;`, matching the
item's pattern. Patterns (case-insensitive):

- **PRESS RELEASE**: `^press release\b` or `for immediate release`.
- **FINANCIAL STATEMENTS**: `(consolidated |group |company )?(income
  statement|statement of (profit or loss|comprehensive income|
  financial position|operations)|balance sheet)` or
  `\(loss\)/profit for the (year|period)` or `\(loss\)/profit per share`.
- **RESULTS ANNOUNCEMENT**: `results announcement|announces? .{0,40}
  results|financial results for|earnings announcement|interim
  results|annual results|half-year(ly)? results|quarterly results|
  preliminary results`.
- **GOVERNANCE NOTICE**: `notice of (the )?(annual |extraordinary )?
  general meeting|annual general meeting|extraordinary general
  meeting|changes? in (the )?board|appointment of .{0,30}director|
  director resignation|resignation of .{0,30}director`.
- **DIVIDEND AND CAPITAL RETURN**: `dividend (declaration|
  announcement|payment)|declares? .{0,30}dividend|share repurchase|
  share buy-back|buyback program|capital return`.

Taxonomy names (the canonical heading phrases the item carries in
`domain/forms/families/current/taxonomy.py`) are the heading forms
of these patterns, per item, as listed in the Step 19 record.

## Validation bar for Step 19 (stated in advance)

Measured on the held-out slice only (199 filings), rules exactly as
drafted above, at 8 workers on Colab High-RAM:

- **Precision >= 0.85 per item**: every heading-anchored hit in the
  held-out slice is human-verified against its filing's text; a hit
  is correct when the named structure is what the heading announces
  (e.g. an assay-results headline is not a results announcement).
- **Coverage >= 0.40 per item**: anchored hits divided by oracle-v2
  hits, where oracle-v2 is the item's loose pattern applied to any
  line of <= 140 chars (not full text — full-text mentions of e.g.
  "dividend" include non-announcements and are not the structure's
  population). Results announcement's oracle-v2 additionally counts
  any heading line containing `results` together with a period word
  (quarter, annual, interim, half, fiscal, financial, operating).
- An item clearing both is adopted; an item missing either is
  dropped and recorded with its numbers. If no item clears, nothing
  is adopted and this record plus the validation record stand as
  the no-taxonomy disposition.
