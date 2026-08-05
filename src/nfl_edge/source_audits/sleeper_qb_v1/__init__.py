"""Sleeper QB source-audit v1 package.

Modules:

* ``ids`` - deterministic identifier helpers.
* ``normalize`` - QB-only filter and stable field projection.
* ``evidence_states`` - audit-only classification of QB evidence.
* ``crosswalk`` - Sleeper-to-nflverse stable-ID match.
* ``changes`` - snapshot-to-snapshot change detection.
* ``freshness`` - freshness / staleness states.
* ``ho_game`` - Hall of Fame Game resolver and observation record.
* ``metrics`` - reliability metrics aggregator.
* ``report`` - markdown / JSON report generator.
* ``pipeline`` - end-to-end bounded orchestrator.

This package is intentionally isolated from ``nfl_edge.models``,
``nfl_edge.backtest``, and ``nfl_edge.evaluation``. It must not be
imported from any production scoring path.
"""
