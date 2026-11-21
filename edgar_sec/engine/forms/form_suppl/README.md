# engine/forms/form_suppl

Review analysis for `SUPPL` (MJDS prospectus supplements): the cover is
the supplement caption block — the general-instruction reference naming
the base form (F-9 II.K / F-10 II.L), the file number, the supplement
kind, and the base-prospectus date chain — plus a census of the
supplement's prospectus headings.

Entry points:

- `analysis.analyze_case(case_dir, record)` — one case → report dict
  with `form_suppl` caption fields and anomalies.
- `analysis.summarize_cases(cases)` — the `form_suppl` scorecard.
