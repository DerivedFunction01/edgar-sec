# measurement

The measurement-protocol driver set, consolidated from the Step 4
and Step 6 programme workspaces (refresh Step 2): draw, collect,
sample, merge, score, and the blind re-read pair. Drivers are
step-parameterized, never step-named — every constant that differed
between steps (seeds, catalog snapshot, exclusion dirs, file prefix,
sample caps, baseline readings, workdir) lives in a config JSON
under `configs/`; a driver run is:

    python3 -m tools.measurement.<driver> --config configs/<step>.json <args>

- `drive_draw` — DuckDB fresh-accession draw over the published
  filing-catalog extracts (argv: out_dir, forms, quotas, population).
- `collect` — the landed hand over fresh fixtures: competition
  grouped returns, assembly assignments, TOC refusals, packets, and
  the seeded sweep sample (argv: fixtures_dir, stratum, out_dir).
  This is the current instrument set; the Step 4 generation's
  gate-on/gate-off competition pair is superseded by it (its grouped
  returns are the identical shape).
- `sample` — grouped + assembly samples, seeded and band-stratified;
  with `aoci_variant` in config, also the Step 4 differing-claims
  aoci sample from the collect's on/off returns (argv: results_dir).
- `merge` — slice verdicts merged against packets with set-equality
  verification (workdir from config).
- `score` — per-stratum pricings through the protocol machinery,
  with deltas against the config's `baseline_results` readings
  (argv: results_dir, verdicts_dir).
- `reread_build` / `reread_score` — the blind re-read: seeded
  subsample under blind IDs, then flip/class-agreement scoring
  (workdir and seed from config).

Proof of the move: re-running `merge` and `reread_score` from this
package over the sealed Step 6 workspace reproduces its recorded
`verdicts-final/` and `reread-results.json` outputs exactly.
