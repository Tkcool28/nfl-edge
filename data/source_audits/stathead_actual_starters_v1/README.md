# Stathead actual-starter source audit v1

This directory preserves source material for the 2018-2024 historical **actual starting-QB** oracle dataset.

- `raw/` is immutable source material.
- `extracted/` contains deterministic table extraction only; it is **not** a cleaned starter ledger.
- Future reconciliation/cleaning outputs must be written as new derived files. Existing historical datasets must not be edited in place.

The Stathead query is postgame evidence and is allowed only for `ORACLE_STARTER_IDENTITY_ONLY`. It must never be represented as historical pregame expected-starter evidence.

The currently preserved upload covers ranks 1-200. Full 1-3921 preservation remains a prerequisite before cleaning is treated as complete.
