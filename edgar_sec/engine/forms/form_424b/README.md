# engine/forms/form_424b

Review analysis for the merged Rule 424 prospectus family (`424B`):
cover-header extraction (424(b)/(a) rule reference, registration
number, registrant, document kind, offering terms) and taxonomy
section segmentation over `analyze_form_case`.

Entry points:

- `analysis.analyze_case(case_dir, record)` — one case → report dict
  with `form_424b` fields and anomalies.
- `analysis.summarize_cases(cases)` — `form_424b` scorecard counts.
- `analysis.build_parser` — the `review analyze` plugin CLI.
