# engine/forms/form_425

Review analysis for the Rule 425 communication family (`425`):
header extraction (filed-by filer, subject company, commission file
number, Rule 425 / Rule 14a-12 references) over `analyze_form_case`.
The body is the filed communication itself and carries no taxonomy.

Entry points:

- `analysis.analyze_case(case_dir, record)` — one case → report dict
  with `form_425` fields and anomalies.
- `analysis.summarize_cases(cases)` — `form_425` scorecard counts.
