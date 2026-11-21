# engine/forms/form_mjds

Review analysis for the MJDS families (`F-7`, `F-8`, `F-9`, `F-10`,
`F-80`): one shared analyzer over the wrapper cover — facing-sheet
fields, the Rule 467 effectiveness election from the cover checkmarks,
tail item segmentation per the form's assigned taxonomy, and, for
`F-9`/`F-10`, the in-body shelf-prospectus heading census.

Entry points:

- `analysis.analyze_case(case_dir, record)` — one case → report dict
  with `form_mjds` fields and anomalies; the family resolves from the
  record's form through the alias map.
- `analysis.summarize_cases(cases)` — per-family `form_mjds`
  scorecards.
