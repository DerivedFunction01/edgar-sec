"""Tables: protection, geometry conversion, false-table rejection, policies.
Split on who may rewrite a table: `protection` guarantees tagged table bytes survive untouched,
the rest decide boundaries and convert or unwrap.
"""
