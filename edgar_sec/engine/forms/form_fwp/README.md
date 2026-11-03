# engine/forms/form_fwp

Review analysis for the free writing prospectus family (`FWP`):
Rule 433 header extraction (issuer, guarantor, registration statement
numbers, terms-table CUSIP) and taxonomy section segmentation over
`analyze_form_case`.

Entry points:

- `analysis.analyze_case(case_dir, record)` — one case → report dict
  with `form_fwp` fields and anomalies.
- `analysis.summarize_cases(cases)` — `form_fwp` scorecard counts.
