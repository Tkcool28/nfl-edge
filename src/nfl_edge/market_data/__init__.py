"""nfl_edge.market_data — RAW historical sportsbook market acquisition.

This package PREPARES (freezes the manifest, derives the request plan, and
provides a safe resumable runner for) the authoritative 2020--2024 historical
The Odds API acquisition. It performs no bulk pull, writes no normalized
market tables, inspects no outcomes, and never touches the sealed 2025
holdout or any frozen football model.
"""