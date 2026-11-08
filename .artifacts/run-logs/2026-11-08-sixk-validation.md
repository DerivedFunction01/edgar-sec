# 6-K taxonomy validation and adoption — Step 19 (item 17)

Validation drive 2026-11-08 on Colab High-RAM (session
ruby-anchor-64, caller secforms:nw17), rules exactly as drafted in
the Step 18 census record
(`.artifacts/run-logs/2026-11-08-sixk-census.md`), applied to the
held-out slice only (199 filings, md5(accession) mod 5 < 2, fixed in
Step 18 before drafting) from the census run's on-session cache —
no refetch. Workers 8 (the census fetch configuration the cache was
built under); the validation pass itself is a bounded re-measure over
199 cached texts, peak RSS 37.4 MB.

## Findings

1. **One item clears the bar and is adopted: PRESS RELEASE**
   (precision 1.000, coverage 0.589). The 6-K profile splits from
   the shared 8-K profile: `FORM_6K_ITEMS` lands in
   `domain/forms/families/current/taxonomy.py`, the 6-K processing
   entry carries it, a `PRIMARY_PROFILE_6K` stands beside the 8-K
   profile, and the 6-K cover profile carries the item as its
   structural heading with `FORM_6K_DERIVED` attached. A 6-K filing
   whose exhibit is headed "Press Release" / "For Immediate Release"
   now renders with an item the shared profile previously could not
   name (the 6-K entry previously carried no taxonomy items at all).
2. **Four drafted items miss the bar and are dropped**, each on its
   own numbers below. Financial statements is the near miss:
   coverage exactly at the bar (0.400) but precision 0.833 — the
   false hits are discussion and policy headings ("Balance Sheet
   and Financial Leverage", "Income Statement Presentation"), not
   statements. The IFRS statement vocabulary is real (Step 18
   finding 3) but a heading-only rule cannot separate statements
   from sections about statements at the stated precision; the
   item is dropped, not tuned — the bar was stated in advance.

## Per-item measurements vs the Step 18 bar

Bar: precision >= 0.85 and coverage >= 0.40 on the held-out slice.
Precision is human verification of **every** heading-anchored hit
(99 hits reviewed line-by-line below); coverage is anchored hits /
oracle-v2 hits as defined in the census record.

| Item | Hits | Oracle-v2 | Coverage | Precision | Verdict |
|---|---|---|---|---|---|
| PRESS RELEASE | 43 | 73 | 0.589 | 43/43 = 1.000 | **adopted** |
| FINANCIAL STATEMENTS | 18 | 45 | 0.400 | 15/18 = 0.833 | dropped — precision |
| GOVERNANCE NOTICE | 13 | 28 | 0.464 | 10/13 = 0.769 | dropped — precision |
| DIVIDEND AND CAPITAL RETURN | 10 | 47 | 0.213 | 8/10 = 0.800 | dropped — both |
| RESULTS ANNOUNCEMENT | 15 | 65 | 0.231 | 9/15 = 0.600 | dropped — both |

False-hit classes, by item (accessions in the drive output):
- Financial statements (3 FP): balance-sheet discussion headings
  (0000950127-02-000609, 0001193125-07-163539) and an accounting
  policy heading (0001104659-14-014959).
- Governance notice (3 FP): prose fragments reporting a past
  meeting, not a notice (0000950127-02-000609,
  0001012870-99-004649, 0001292814-26-001940).
- Dividend and capital return (2 FP): a withholding-tax prose
  fragment (0001144204-07-064535) and a truncated
  "Share capital returned to" line that does not announce the
  structure (0001028596-99-000134).
- Results announcement (6 FP): two reserves/assay "results"
  headlines (0001176256-19-000350, 0001279569-24-000173), two
  prose fragments (0000950123-04-002148, 0001012870-99-004649),
  and two press-release lead sentences that are results
  announcements in substance but not headings
  (0000950157-99-000639, 0001193125-04-182372) — counted false
  under the heading rule as drafted.

## Adoption wiring

- `edgar_sec/domain/forms/families/current/taxonomy.py`:
  `FORM_6K_ITEMS` (one item, `PRESS RELEASE`, names
  "press release" / "for immediate release"), `ITEMS_6K`,
  `FORM_6K_DERIVED`.
- `edgar_sec/domain/forms/families/current/profiles.py`:
  `PRIMARY_PROFILE_6K` beside `PRIMARY_PROFILE_8K`.
- `edgar_sec/domain/forms/families/processing_profiles.py`: the
  6-K catalog entry now carries `taxonomy_items=FORM_6K_ITEMS`
  (previously empty), so the family's analysis path
  (`engine/forms/analysis.py`, which consumes
  `entry.taxonomy_items`) detects the item for 6-K filings.
- `edgar_sec/engine/forms/cover/profiles.py`: the 6-K cover
  profile's structural headings are the 6-K item set (previously
  empty) and `FORM_6K_DERIVED` is attached as its derived
  taxonomy.
- Per-item fixtures from census exemplars:
  `tests/fixtures/sixk_press_release_0000912282-05-000713.txt`
  ("For Immediate Release") and
  `tests/fixtures/sixk_press_release_0000899797-02-000224.txt`
  ("Press Release"); the section detector names
  `ITEM PRESS RELEASE` on both (its identifier convention for
  title-only items), and names no item on a press-release-free
  6-K text.

## Verification

Local gate (TMPDIR=~/workspace/.tmp-gate):
`check.py tests/domain/forms tests/engine/forms --workers 2` —
1993 passed, 21 scanner checks clean, ruff format/lint clean.
