"""Bounded, read-only audit harness for live external sources.

This subpackage contains the audit orchestrator, metrics, and report
generator for the August 2026 Sleeper QB source-feasibility audit. It
is **not** wired into the model pipeline and must remain isolated from
``nfl_edge.models``, ``nfl_edge.backtest``, and
``nfl_edge.evaluation``.
"""
