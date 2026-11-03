# engine/forms/form_fn

Review analysis for `F-N` (appointment of agent for service of
process): field extraction only — the filer, the original/amended
mark, the conjunction filing named in item C, the jurisdiction, and
the appointed agent — read from the printed form's lettered items.

Entry points:

- `analysis.analyze_case(case_dir, record)` — one case → report dict
  with `form_fn` fields and anomalies.
- `analysis.summarize_cases(cases)` — the `form_fn` scorecard.
