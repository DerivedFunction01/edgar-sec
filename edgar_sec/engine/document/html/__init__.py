"""High-throughput HTML parsing, cleaning, and plain-text projection.

The package is split on the seam that matters — which representation of the
document a pass is looking at. `tags` owns the classification vocabulary every
other module shares; `tree` is the `selectolax` access surface; `cleaner`
removes transport noise; `breaks` keeps page structure alive across
projection; `normalizer` turns markup into text.
"""
