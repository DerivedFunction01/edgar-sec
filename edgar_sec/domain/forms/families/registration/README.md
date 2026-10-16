# registration

Layer 1 registration statement form family domain package.

## Purpose

Defines domain contracts, Item 601 exhibit mappings, statutory Part and Item taxonomies, and cover checkbox schemas for registration statements filed under the Securities Act of 1933, principally Form S-1 and its pre/post-effective amendments.

This package encapsulates the distinct structural boundaries of registration statements—where a facing sheet transitions into a preliminary prospectus, Table of Contents, or Part I—without leaking registration-specific anchors into Exchange Act periodic reporting profiles.

## Contracts

- **Statutory Part Partitioning**: Form S-1 separates into Part I (Items 1–12A, prospectus material) and Part II (Items 13–17, non-prospectus undertakings, exhibits, and signatures).
- **Item 601 Authority**: Exhibit requirements strictly follow the unified Item 601 authority table (Column 1 for S-1) under Regulation S-K.
- **Dual Checkbox Scope**: Governs Securities Act Rule elections (Rules 415, 462(b), 462(c), 462(d)) alongside Exchange Act Rule 12b-2 filer status and emerging growth company transition rules.
- **Downward-Only Dependency**: Strictly confined to Layer 1 domain primitives and Layer 0 foundation utilities; imports no upper layers.

## Deliberate gaps

- **Specialized Shelf Registrations**: Detailed taxonomy definitions for Form S-3, S-4, S-8, and foreign issuer registration statements (Form F-1) are deferred to subsequent family extensions.
- **XBRL Exhibit Ingestion**: Interactive data file exhibit validation for registration statements relies on standard Item 601 ledger entries and defers registration-specific taxonomy rules.
