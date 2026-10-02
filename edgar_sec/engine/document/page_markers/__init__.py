"""Page-marker detection, validation, and policy for normalized documents.

A normalized document still says which page it is on. Those claims are
printed page furniture — an SGML `<PAGE>` tag, a wrapped label, a `page N of M`
line, a banner that recurs at the same distance from every page — and every
stage downstream wants the text without them, or wants the page structure
preserved as explicit tokens.

The package answers three questions in order. `detector` finds what the
document claims about its own pagination. `sequence` and `templates` decide
which claims are corroborated well enough to act on. `policy` then applies a
declared policy to the validated decisions and records provenance for
everything it touched. `candidates` owns the contextual scan and the geometry
that keeps a table from reading as a page sequence, `units` classifies the line
stream well enough to tell a table from a paragraph, `artifacts` owns the
canonical token format and its sidecar metadata, and `signatures` owns the
layout region that must survive a reflow intact.
"""
