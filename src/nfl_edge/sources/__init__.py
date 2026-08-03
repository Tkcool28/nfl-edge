"""Live external source-audit clients for NFL Edge.

This subpackage is intentionally separate from ``nfl_edge.data`` (which
handles the frozen, auditable historical inputs). The ``sources`` package
contains **read-only**, **isolated**, **non-production** clients used
only to evaluate whether a live source is fit for future use. They must
not import from ``nfl_edge.models``, ``nfl_edge.backtest``, or
``nfl_edge.evaluation``.

The Sleeper client lives here because the August 2026 bounded live
audit is a source-feasibility check, not a frozen-data ingestion
pipeline.
"""
