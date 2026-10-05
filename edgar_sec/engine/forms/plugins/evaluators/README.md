# `edgar_sec/engine/forms/plugins/evaluators` — per-family triage

Three functions decide whether a normalized document is worth publishing as
itself.

## Purpose

An annual report that incorporates its Exhibit 13 financials by reference does
not contain those financials. Publishing it whole yields a document whose
statements are missing, with nothing in the output to say so. `evaluate_annual`
detects that condition. The other two evaluators hold only metadata shortcuts;
both ignore their `text` argument outright.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `annual.py` | `evaluate_annual` — Exhibit 13 incorporation-by-reference detection. |
| `quarterly.py` | `evaluate_quarterly` — the XBRL-year and HTML/ASCII size-ceiling shortcuts. |
| `current.py` | `evaluate_current` — unconditional proceed. |
| `__init__.py` | One-line docstring only. No re-exports, per AGENTS.md §1.2. |

## Contracts

- **Every evaluator returns a complete `EvaluatorDecision`**, carrying the action,
  the category, a human-readable reason, and a confidence. Category and reason
  are part of the contract, not decoration: several paths return the same action
  and differ only in what they say, so a consumer reading only `action` cannot
  tell them apart.
- **`evaluate_annual` is the only evaluator that reads `text`.** It returns
  `REFETCH_SUB_DOC` when an Exhibit 13 mention falls inside a delegation-verb
  window — the financials live in an exhibit and this document should be
  refetched, not published whole. Its reason embeds a quoted snippet.
- **`evaluate_quarterly` and `evaluate_current` never read `text`.** Both
  bind it to `_` and decide on metadata alone, so both return `PROCEED` /
  `standard_full` when no metadata is supplied.
- **An unknown family is never an error.** It routes to `evaluate_generic` via
  the registry, not by any check inside these modules.

## Public surface

- `evaluate_annual` — `annual.py`.
- `evaluate_quarterly`, `HTML_SIZE_CEILING`, `ASCII_SIZE_CEILING` —
  `quarterly.py`.
- `evaluate_current` — `current.py`.

## Command surface

None. Library package, no CLI.

## Production consumers

`edgar_sec/pipelines/document_storage/processor.py`, via
`plugin.evaluator(result.text)`.

## Tests

- `tests/engine/forms/plugins/evaluators/test_annual.py`
- `tests/engine/forms/plugins/evaluators/test_quarterly.py`
- `tests/engine/forms/plugins/evaluators/test_current.py`

## Deliberate gaps

- **`filing_year`, `raw_length`, and `is_html` are unreachable in production.**
  The SPI is `plugin.evaluator(result.text)`, so the XBRL year shortcut and both
  size ceilings cannot fire. Closing this needs `FilingProcessor` to pass
  context, which is a caller change rather than a change to the evaluators.
- **`int(filing_year)` is unguarded.** A non-numeric year raises `ValueError` out
  of the evaluator and `2013.5` silently coerces to `2013`. Both preserved.
- **20-F has no evaluator branch here.** It resolves to `evaluate_generic`, while
  normalization treats it as annual — see the parent README.
- **The parenthesised `Exhibit (13)` spelling never matches.** The alternation is
  wrapped in a trailing `\b` and the branch ends on `)`, and a word boundary
  cannot sit between `)` and ordinary prose. The same `\b` is what stops
  `Exhibit 130` from matching, so neither branch can be dropped without changing
  behaviour. Pinned by `test_the_parenthesised_spelling_is_unreachable_in_v1`.
- **`DecisionAction.SKIP_HARD_STUB` is never emitted** by any of the three.
