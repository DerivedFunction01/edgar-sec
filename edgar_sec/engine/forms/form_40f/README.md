# engine/forms/form_40f

Review analysis for Form `40-F`: cover extraction (registrant, the
Section 12 vs Section 13(a)/15(d) election decision, the
furnished-information marks) and furnished-document segmentation by
kind (annual information form, financial statements, MD&A, other
exhibits) over `analyze_form_case`. The form carries no SEC item
taxonomy; component bodies pass through the generic render.

Entry points:

- `analysis.analyze_case(case_dir, record)` — one case → report dict
  with `form_40f` fields and anomalies.
- `analysis.summarize_cases(cases)` — `form_40f` scorecard counts.
