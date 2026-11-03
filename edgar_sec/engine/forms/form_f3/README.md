# engine/forms/form_f3

Review analysis for the shelf registration family (`F-3`, including
the ASR, DRIP, POS and MEF variants): facing-sheet field extraction
(registrant, registration number, document kind, fee-table presence,
CUSIP) and taxonomy section segmentation over `analyze_form_case`.

Entry points:

- `analysis.analyze_case(case_dir, record)` — one case → report dict
  with `form_f3` fields and anomalies.
- `analysis.summarize_cases(cases)` — `form_f3` scorecard counts.
