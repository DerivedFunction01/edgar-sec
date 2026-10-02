"""The reflow entry point: segmentation, decision, and rendering.

`rewrapper.py` is the whole stage. It masks the blocks it must not touch,
segments the rest into blocks, decides each block through the cascade, resolves
table boundaries, and renders the exact text each decision calls for. The
output is a pure function of the input text, the body boundary, the page
analysis, and the policy — no clock, no filesystem, no randomness.
"""
