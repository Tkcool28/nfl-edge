# Frozen baseline fixtures

The baseline fixture remains hand-auditable and intentionally small. It includes two teams across multiple weeks, a bye, a neutral-site game, a starting-QB change, a rookie/zero-sample QB, depth records around a cutoff, and a future game that must not affect earlier rows.

Baseline files:

- `games.csv`
- `team_game_stats.csv`
- `qb_game_stats.csv`
- `depth_chart_snapshots.csv`

Feature-pipeline v1 fixtures extend those cases without changing the frozen baseline:

- `feature_games_v1.csv` — regular season, bye, tie, neutral site, future unplayed game, postseason, and Tuesday unusual-date example.
- `feature_team_game_stats_v1.csv` — two team rows per completed fixture game for shift-before-roll poisoning tests.
- `feature_qb_game_stats_v1.csv` — starter change, rookie/zero-volume QB, and missing player ID.
- `feature_depth_evidence_v1.csv` — one second before, exactly at, and one second after cutoff plus conflicting top depth evidence.
- `feature_postgame_evidence_v1.csv` — weekly stats/snap-count evidence retained for audit but prohibited from raising pregame certainty.

All fixtures are static repository data. Tests must not regenerate them from a network source.
