"""Conservative ASCII reflow and untagged-table tagging.

The stage that decides, for each block of plain-text filing content, whether to
leave it exactly as it is, join its hard-wrapped lines into one paragraph, or
wrap it in `<TABLE>` markers. It is deliberately biased towards leaving content
alone: a missed unwrap is legible, a collapsed table is not.

The package is split on what each part *is*, not on call order. `features`
measures a block — one compact geometry record, and one full memoized feature
context. `rules` holds the 44 calibrated thresholds and the ordered cascade that
combines them into a decision. `engine` runs the stage. `types` holds the
decision vocabulary and the policy the caller injects, which is how this package
learns about cover and taxonomy vocabulary without importing any of it.

No form family, no statement taxonomy, and no page-marketing vocabulary is
imported here; the caller supplies those predicates. `__init__.py` is a docstring
per `AGENTS.md` §1.2, so consumers import the leaf they need.
"""
