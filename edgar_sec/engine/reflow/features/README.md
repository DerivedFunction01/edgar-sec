# `edgar_sec/engine/reflow/features` — block measurement

## Purpose

Computes text-layout and geometry measurements for ASCII blocks consumed by reflow and table
resolution.

## Contracts

- **Leading indentation is not treated as internal column spacing**: Only inter-column spacing is measured.
- **Shared-column measurements reflect repeated alignment**: Based on row-to-row consistency.
- **Form signals are supplied through the policy**: Checkbox and financial-bridge predicates injected by caller.
- **Checkmark evidence cannot be removed by caller predicates**: Policy predicates cannot erase checkmark signals.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

## Deliberate gaps

- **`numeric_cell_rows` has a type annotation that does not match its runtime value.**
- **Measurements are ephemeral.** This package does not publish a persisted feature artifact.
