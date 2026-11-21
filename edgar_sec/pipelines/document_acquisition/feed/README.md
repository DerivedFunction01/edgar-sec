# feed

Layer 4 acquisition subpackage for the Feed-archives source leg.

## Purpose

This package stores per-day SEC Feed tarballs in the shared bulk-archive store and inventories their SGML bundles into the published `feed_inventory` relation the planning machinery consumes. It acquires no payload: inventoried bundles enter acquisition snapshots only through pinned plans over the published inventory.

## Contracts

- **Inventory source only**: Nothing enters the document store from this leg; the sole published product is the inventory relation.
- **Streamed inventory**: Tarballs are read in stream mode one bundle at a time; only a bounded header segment of each bundle is parsed, and a day's tarball is never held whole in memory or extracted to disk outside the store.
- **Branch-isolated, delta-only publication**: The relation publishes on the dedicated `feed_archives` DAG branch through the anti-join publish, so re-publishing known bundles is a no-op and run-publication lineage on `main` is untouched.
- **Resume by content identity**: A day is skipped only when it is both in the store by its source URL and its archive SHA is already in the published inventory.

## Deliberate gaps

- **No Feed payload leg**: Turning an inventoried bundle into an acquired payload still requires a pinned plan; the firehose never becomes an unpinned acquisition path.
