# `edgar_sec/engine/reflow/features` — block measurement

## Purpose

Computes text-layout and geometry measurements for ASCII blocks consumed by reflow and table
resolution.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `context.py` | Block-level text measurements and derived properties. |
| `geometry.py` | Compact layout and numeric-cell measurements. |

## Contracts

- Leading indentation is not treated as internal column spacing.
- Shared-column measurements reflect repeated alignment across rows.
- Form-specific checkbox and financial-bridge signals are supplied through the policy.
- Checkmark evidence cannot be removed by a caller-supplied predicate.

## Public surface

- `BlockContext` — public block-level measurement interface (`context.py`).
- Geometry helpers and the compact feature record (`geometry.py`).

## Command surface

None. This is a library package with no CLI.

## Tests

Mirrored coverage lives under `tests/engine/reflow/features/`.

## Deliberate gaps

- **`numeric_cell_rows` has a type annotation that does not match its runtime value.**
- **Measurements are ephemeral.** This package does not publish a persisted feature artifact.
