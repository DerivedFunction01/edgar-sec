# cascade

## Purpose

The classification cascade and the claiming competition: `classify` runs the
tiered cascade over the measured registry; `competition` seats the composed
claiming chain; family and geometry scoring name each table's family, flavor,
and kind with an evidence trail. The per-table scoring modules live in
`scoring/`; the geometry text and profile-scoring primitives live in
`geometry/`.

## Contracts

- **Classification is a tiered cascade over a measured registry**: specific
  policy-supplied winners first, then per-family evidence with quota caps on
  correlated groups; negative evidence scores as a cross-family term, never
  a gate.
- **The claiming chain is one composed return**: primary gate, then the PPE
  veto pass over the gated set, then the precision pass — neither pass reads
  the other's claim presence.
- **Signature competition is scored claiming over measured profiles**:
  a claim issues only when the family's own profile (assembled in
  `core.subjects.signature_profiles`) dominates the geometry's text and the foreign
  profile mass is negligible or explained by a measured containment edge.
- **A filing is classified as a constellation, not table by table**:
  confident core anchors bound the statement zone, and a note satellite's
  win before the first anchor is discounted.

## Deliberate gaps

- **Subtotal promotion by arithmetic closure is not decided here**: a
  computed row without a total or subtotal label stays data until the
  validation layer proves the closure (the parent package's gap, held here).
