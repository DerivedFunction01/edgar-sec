# `edgar_sec/engine/reflow/features` — block measurement

## Purpose

Computes text-layout and geometry measurements for ASCII blocks consumed by reflow and table
resolution.

## Contracts

- Leading indentation is not treated as internal column spacing.
- Shared-column measurements reflect repeated alignment across rows.
- Form-specific checkbox and financial-bridge signals are supplied through the policy.
- Checkmark evidence cannot be removed by a caller-supplied predicate.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

## Deliberate gaps

- **`numeric_cell_rows` has a type annotation that does not match its runtime value.**
- **Measurements are ephemeral.** This package does not publish a persisted feature artifact.
