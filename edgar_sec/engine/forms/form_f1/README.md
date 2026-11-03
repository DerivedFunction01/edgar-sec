# engine/forms/form_f1

Review analysis for the foreign registration families (`F-1`, `F-2`):
facing-sheet field extraction (registrant, registration number,
document kind, fee-table presence, CUSIP) and taxonomy section
segmentation over `analyze_form_case`.

Entry points:

- `analysis.analyze_case(case_dir, record)` — one case → report dict
  with `form_f1` fields and anomalies.
- `analysis.summarize_cases(cases)` — `form_f1` scorecard counts.
