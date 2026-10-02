"""Layer 5: read-only, operator-facing consumers of published artifacts.

An app reads what a pipeline already published and never publishes, transforms,
or fetches anything. It is not a batch layer: no chunks, no plan, no worker, no
resumability, so none of AGENTS.md §4's pipeline contracts bind it.
"""
