"""Scalar feature extraction for a block of ASCII lines.

Two views of the same block. `geometry.py` computes a compact record in one
pass over the lines, for the resolver's table-discipline gate. `context.py`
computes the full memoized feature set, for the rule cascade. Both describe
layout, density, and grammar; neither decides anything.
"""
