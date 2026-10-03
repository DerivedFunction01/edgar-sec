"""The reflow entry point: segmentation, decision, and rendering.
`rewrapper.py` is the whole stage, and its output is a pure function of the input text, body
boundary, page analysis, and policy - no clock, no filesystem, no randomness.
"""
