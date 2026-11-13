# extraction

## Purpose

The successor table-extraction package: it wraps each rendered `TableGeometry` in a
`TableContext` carrying the evidence gathered around the grid (caption stack, scale,
document location, surrounding prose, page-break evidence), and structures the grid
into typed rows with per-column period bindings derived from the whole header stack.
A tiered classification cascade over a measured registry names each table's family,
flavor, and kind with an evidence trail; the assembly layer groups a filing's
classified tables into logical statements and arbitrates their relations.

## Contracts

- **Periods bind from the whole header stack**: spanning group rows and per-column
  date or year rows compose into one label per value column; `header_row_count` is
  never used as the binding source. A value column no header cell covers binds an
  explicit unknown period, never a guessed one. Adjacent numeric columns that never
  carry a value in the same row are one logical column — the currency-marker column
  and the value column it serves merge before binding.
- **The caption stack is data, never a single stripped candidate**: company, titles,
  audit status, scale, and continuation are parsed out of it, including facts packed
  into one merged caption cell and scale phrases riding header rows.
- **Scale is data or explicit unknown**: a table's scale is a parsed `Scale` or
  `None`; no consumer re-derives it from rendered text.
- **Row kinds are structural**: section, subtotal, total, parenthetical, and data are
  decided from label and value shape alone; family vocabulary enters at the family
  layer, not here.
- **Values read through `clean_numeric`** over the geometry the split-paren merge
  already canonicalized; the raw row is always carried alongside the typed values.
- **Classification is a tiered cascade over a measured registry**: specific
  policy-supplied winners first (anchors and label conjunctions), then per-family
  evidence with quota caps on correlated groups; every pattern, bound, and
  exclusion in the registry carries its measured value and a provenance reference
  to the calibration record it came from. Negative evidence scores as a
  cross-family term, never a gate. Arithmetic identities priced in the registry
  contribute confirmation evidence on closure and a zero-point signal on
  failure — never a gate, veto, or standalone assignment. Row bounds bind at
  the assembled level only.
- **The engine owns no form vocabulary**: anchors, label rules, and location
  expectations are injected through the classification policy; with no location
  priors injected, the location tier contributes nothing.
- **Assembly is relational arbitration over measured relations**: split
  fragments join on continuity signals and row bounds bind the assembled
  group; a subset family fires inside its measured parent only as a section;
  each family holds one main slot per filing, ranked, with further groups
  kept as variants; relations carry registry standing only where a census
  measured them, and every arbitration act records its provenance.
- **Region is hard context**: a geometry inside a signature region is never a
  statement candidate, whatever its vocabulary scores; regions derive from
  filing position, section membership, and the forms layer's signature
  classifier unless a builder stamps one on the context.
- **A filing is classified as a constellation, not table by table**:
  confident core anchors bound the statement zone, and a note satellite's
  win before the first anchor is discounted; a family's registered note
  home assigns only tables no scored family claims; a core variant whose
  totals conflict with its main's is tagged a second statement set, never
  silently a fragment.

## Deliberate gaps

- **Subtotal promotion by arithmetic closure is not decided here**: a computed row
  without a total or subtotal label stays data until the validation layer proves the
  closure.
- **Location priors are not yet supplied**: the annual form family's location
  expectations land with their own module; until then the surface runs on
  vocabulary and shape evidence alone.
