# engine/forms/form_f6

Review analysis for `F-6` (depositary share registration): dual-party
cover extraction — the issuer of the deposited securities and the
depositary, each named above its own caption — the Rule 466
effectiveness decision from the cover checkmarks, and segmentation of
the cross-reference sheet and Part II tail.

Entry points:

- `analysis.analyze_case(case_dir, record)` — one case → report dict
  with `form_f6` fields and anomalies.
- `analysis.summarize_cases(cases)` — the `form_f6` scorecard.
