"""Cover-page recognition: boundary, TOC, healing, table cleaning, checkmarks.

An SEC filing opens with a cover page that carries registrant identity, filer
status, and report-period checkboxes, followed by a table of contents and the
substantive body. This package owns the decisions about where each of those
regions ends and what may be rewritten inside them.

Three invariants hold across every subpackage:

* **Bounded.** A cover decision never extends past the verified boundary, and a
  rejected boundary is reported rather than guessed.
* **Profile-driven.** Evidence capability and vocabulary come from a
  :class:`~edgar_sec.engine.forms.cover.models.CoverBoundaryPolicy` and typed
  evidence packs, never from a hardcoded form name.
* **Inspectable.** Every decision carries the evidence rows that produced it, so
  a surprising boundary can be traced to the signal that caused it.
"""
