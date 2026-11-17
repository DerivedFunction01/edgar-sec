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
  failure — never a gate, veto, or standalone assignment. Shape row bounds
  bind at the assembled level only; the form-test stage's per-family row
  envelope is a separate scored signal. The scored set is every family with
  measured vocabulary plus every family the form-test stage tests, so a
  tested family can always be named by the cascade.
- **The engine owns no form vocabulary**: anchors, label rules, and location
  expectations are injected through the classification policy; with no location
  priors injected, the location tier contributes nothing.
- **The subject-evidence map is data, not code**: `subject_evidence.py` loads
  the versioned flat map beside the registry (per-term support/share/confidence
  by family and text channel, measured containment edges, header/title
  inheritance pricing, and channel weights); it carries free-text evidence
  only, and arithmetic closure appears in it solely as a corroboration-only
  policy, never as negative evidence.
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
- **Contexts are produced once, by one function**: `context_production.produce_contexts`
  is the only context-production path — corpus builder, pipeline, and facade fast
  path all call it and none assembles a context of its own. Filing-level facts are
  computed once in document normalization and carried on the context: the TOC span,
  the closing span, the region map (the section sequence as seats, including the
  Item 1 seat and the MD&A seat), the exhibit inventory and resolution, and the
  per-document geometry set. A seat re-deriving a filing-level fact is a defect.
  No family profile declares a prose window: prose windows are genre-layer only.
- **The closing span is consumed at the genre seat**: a geometry whose location
  starts inside the filing's carried closing span is genre-refused before any
  family scoring, on that fact alone, beside the TOC refusal; it contributes no
  family scores to its filing.
- **Exhibits resolve through the registry, once**: a family profile's exhibit
  links are registry data; the engine/forms resolver decides candidacy from index
  metadata alone (the domain type-family predicate), confirms bodies only on
  flagged candidates through the body evaluator, and judges delegation by an
  anchor-window scan of the primary. Confirmed exhibits enter production stamped
  with their source document; there is no second resolver.
- **Section position is a genre gate, not evidence**: the declared section
  map rides the classification policy from the forms layer and is applied
  by `section_gate`; a statement-family claim seated in an MD&A or
  directors section is refused by position alone, with the refusal
  recorded in the evidence trail, and every other position is silent —
  location never scores.
- **Document furniture is refused at the genre seat, upstream of all
  claiming**: `genre_seat` consumes the facts context production
  carries (span membership, the front-matter band, per-geometry
  shape and index measurements) and refuses furniture — contents
  and index pages, closing-span and exhibit-index tables, empty
  bodies, folios, and unseated zero-numeric fragments — before the
  cascade scores or the competition claims; furniture is never
  carried as per-family imposters. Both claiming paths consult
  the same seat on the same facts.
- **Table-of-contents shape is a genre refusal, seated before scoring**:
  `toc_gate` measures page-reference rows (the shared TOC row vocabulary,
  explicit page tokens, and increasing bare page numbers) against the
  table's rows; a table inside the filing's cover TOC span (found once
  per filing by the cover finder, stamped on the context at extraction)
  is refused on that fact alone, and a TOC-shaped table outside the
  span only on content — no currency amounts and at least four family
  namespaces across its page-reference rows. A refused table
  contributes no family scores to its filing.
- **Signature competition is scored claiming over measured profiles**:
  each family's signature terms live once, as data, in the
  subject-evidence map (`subject_evidence`), assembled by
  `signature_profiles` with per-term discriminativeness measured over
  the adjudicated corpora; a claim issues only when the family's own
  profile dominates the geometry's text and the foreign profile mass
  is negligible or explained by a measured containment edge — single
  foreign words never discriminate. Arithmetic closure corroborates
  the leading family only; it never vetoes. Within a filing, header
  inheritance and cross-parse ties feed back as context evidence.
- **Derivatives claims are gated on U/A evidence**: a `derivatives_hedging`
  claim issues only when the geometry itself carries underlying/notional (U)
  or accounting-effects (A) evidence under the gate algebra declared as
  registry data in `profiles` (`DERIVATIVES_EVIDENCE_SPECS`: unambiguous bases
  decide alone, ambiguous bases only in accumulation, the equity and NPNS
  exception lists carve their subjects out); strong U/A evidence also reaches
  an otherwise unclaimed plain listing. The same spec evaluates over a typed
  table's full grid through the `derivatives_evidence_gate` form-test kind.
- **Prose-window grain decides what the geometry cannot**: a filer-status
  checkbox fragment is decided from the bounded prose window framing it
  (`prose_window`), never from the fragment's own grid; the window's
  checkbox block is the discriminating grid and the reading carries its
  grain as provenance.
- **Family profiles live once, as data, in the profile registry**: `profiles` is the
  single home of family profiles for exactly the supported set — each profile carries
  its measured support state per stratum, its vocabulary seat, its form-test
  declarations and specs (data only), its gate/seat bindings, its
  exhibit links, and its prose-window permission (none for every family: prose
  windows are genre-layer only). A family outside the registry does not compete:
  absence is the whole mechanism, never a code branch — subsequent_events is an
  adjudicated absence of exactly that kind. Profiles
  carry stratum codes, never form names — form enters only as detected context data.
- **Form tests are registry data, evaluated by one stage**: `form_tests` evaluates
  the declared specs once per table, between context assembly and the vocabulary
  competition, dispatching on the spec's kind only — never on its family; each
  kind's own parameters live in that kind's table in `profiles`, keyed by test_id.
  A family with no declared specs has none. Anchor labels only locate the rows the test runs
  over; the test itself is arithmetic. A passed test scores as evidence in both
  competitions (the `form_test` channel and evidence group); a failed evaluable
  test records a zero-point signal, never a veto or a standalone assignment.
  Three kinds score measured form signals rather than arithmetic: `row_bound`
  (the family's member row envelope, per family, orientation per the measured
  fixed/free map), `signature_absence` (at least one of the family's core
  signature labels present; total absence is the imposter signature), and
  `placement_consistency` (the priced placement conjunctions over the table's
  position in the filing's geometry sequence, `placement`). The three kinds'
  parameter tables live in `form_signal_specs`, keyed by test_id. Placement
  facts are computed from the filing's own first-pass reads inside
  `classify_filing` and applied by re-arbitration; unstamped, placement
  tests are unevaluable.
- **Labor capture is schema-led prose-to-table**: linkage terms generate
  candidate spans and the employee group x contract x union fields bind
  inside a linked span only (`labor_capture`); schedule-header terms are
  field evidence, never generators, rows are text-valued, and an explicit
  negation binds as a zero fact, not a carrier.
- **Residue families claim on content, not title alone**: segment,
  commitments and related-party note-title points land only on grids
  whose own content corroborates the family (`residue_families`); an
  uncorroborated sibling grid in the same note earns no title claim.
- **Commitments claims sit in the geometry-text seat**: the family's
  seat (`commitments_seat`) reads the geometry's own text — a
  payments-due shape anchored on a purchase-obligations row, a
  credit-commitments cluster, or a guarantee schedule — and claims
  only where the carried context seats the geometry in the MD&A
  seat or a note region; a payments-due grid without the purchase
  row and a lone letter-of-credit line earn no claim.
  Segment corroboration reads the whole grid, headers included
  (`GeometryText.grid_text`), and admits a measure grid on any priced
  arm: segment vocabulary, the bare segment word in the grid, the
  reconciliation form (markers plus a total), or segment framing in
  the lead-in (plain, geographic, or disaggregation).
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
