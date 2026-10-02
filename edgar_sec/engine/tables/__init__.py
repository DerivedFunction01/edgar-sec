"""Tables: protection, geometry conversion, false-table rejection, policies.

The package is split on the seam that matters — who is allowed to rewrite a
table. `protection` guarantees tagged table bytes survive untouched; the other
modules decide boundaries, convert rendered HTML, and unwrap layout tables.
"""
