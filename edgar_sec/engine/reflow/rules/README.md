# `edgar_sec/engine/reflow/rules` — reflow decision rules

## Purpose

Defines feature predicates and the rules that classify text blocks for reflow.

## Contracts

- **Decisions combine feature predicates and preserve safeguards.** Tagged or ambiguous
  content is not unwrapped solely on a permissive prose match.
- **Every decision carries evidence and a trace** for downstream rendering and review.
- **Rule order is part of behavior.** Protected structures take precedence over
  permissive prose rules; the final fallback preserves ambiguous blocks.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

## Deliberate gaps

- **No runtime threshold learning or adaptive recalibration.** Predicates are fixed in
  the checked-in feature vocabulary.
- **No statement-quality validation.** Decisions classify layout for rewriting; they do not
  assess the financial correctness of a tagged table.
