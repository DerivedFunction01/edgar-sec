# engine/forms/form_f4

Review analysis for the business-combination registration family
(`F-4`, including the POS and MEF variants): facing-sheet field
extraction (registrant, registration number, document kind, fee-table
presence, CUSIP) and taxonomy section segmentation over
`analyze_form_case`.

Entry points:

- `analysis.analyze_case(case_dir, record)` — one case → report dict
  with `form_f4` fields and anomalies.
- `analysis.summarize_cases(cases)` — `form_f4` scorecard counts.
