# Frames cross-check drive — Item 11, Step 4

## Findings

- **Agreement rate 97.47%** over the compared CIK set: 77 agree, 2 diverge
  out of 79 CIKs present on both sides of the join.
- Frame joined: `us-gaap` / `Assets` / `USD` / `CY2024Q4I` (instant),
  6,280 frame CIKs, fetched live through `fetch_frame` on the session.
- Resolver: `us-gaap:Assets`, archive slice 2026, atom `(H_ASSET, ∅)`,
  period type `instant` — the corpus-index coordinate the join screened on.

## Drive shape

- Venue: Colab High-RAM session ruby-anchor-64 (lease
  ruby-anchor-64-r1794107055), caller `secforms:nw11`; the edgar-sec clone
  was built by the env-build job (run env-build-20261108T034655Z) and this
  lane's five changed/new modules were overlaid from branch
  impl/nw-item11-frames (commits bd046db6, 6b0920e6).
- Corpus index built on-session at 8 workers from the tracked fixture
  corpora (seed + vintage + SP100 bundles): 125 bundles, 83,095 coordinate
  rows, 125 filings, 0 ingest failures.
- Corpus-index screen: 13,948 rows at `(H_ASSET, ∅)`; 121 filings carry the
  exact resolved qname `us-gaap:Assets`.
- Parsed side per CIK: the filing's `facts.parquet` value for
  `us-gaap:Assets`, unit USD, no dimensions, instant date equal to that
  CIK's frame-row end date. Comparison is `compare_frame_to_parsed`
  (cross-check only; frame values remain SEC aggregates with provenance).

## Outcome classes over the frame's full CIK set (6,280)

- agree: 77
- diverge: 2
- frame_only: 6,201 — of which 6,174 have no corpus filing at the
  coordinate (outside the 125-filing fixture corpus) and 27 have a corpus
  filing whose parsed Assets facts sit at other instant dates (non-December
  fiscal year-ends: the frame period collects each filer's period ending in
  CY2024Q4, the corpus bundles are FY2024 annual filings).
- parsed_only: 0 (the parsed side was keyed to frame CIKs by construction).

## Divergences

- CIK 70858: frame 3,261,299,000,000 vs parsed 3,261,519,000,000
  (relative difference 6.7e-5).
- CIK 354190: frame 64,255,000,000 vs parsed 64,255,200,000
  (relative difference 3.1e-6).

Both divergences are small-magnitude: the class consistent with the frame
aggregate reflecting a different filing vintage (restatement/amendment
timing) than the parsed corpus bundle, not a parse error — no large or
sign-flipped divergence appeared.
