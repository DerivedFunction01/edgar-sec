"""Conservative ASCII reflow and untagged-table tagging.
Per block, the stage decides whether to leave it, join its hard-wrapped lines, or wrap it in `<TABLE>` markers, biased toward leaving content alone: a missed unwrap is legible, a collapsed table is not. All form vocabulary arrives on the injected `ReflowPolicy`.
"""
