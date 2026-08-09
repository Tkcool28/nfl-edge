# Stathead actual-starter raw recovery v1

This directory preserves the **raw Sports Reference Stathead Player Game Stats Finder output** used for NFL EDGE Task 04A historical actual-starter reconstruction.

## Source semantics

- Source: `SPORTS_REFERENCE_STATHEAD_PLAYER_GAME_FINDER`
- Query intent: single player games, seasons 2018 through 2024, regular season or postseason, position QB, `Started Game`, sorted by descending Date.
- Raw columns exported by Stathead:

```text
Rk,Player,Day,G#,Week,Date,Age,Team,,Opp,Result,Pos.,Player-additional
```

- `Player-additional` is the Pro-Football-Reference player identifier used for later PFR -> nflverse/GSIS mapping.
- Historical evidence class for accepted downstream starter assignments: `POSTGAME_ACTUAL_STARTER`.
- Historical model usage for accepted downstream starter assignments: `ORACLE_STARTER_IDENTITY_ONLY`.

## Critical raw-data warning

The Stathead result set is **not itself a clean one-row-per-actual-QB-starter ledger**. The raw export contains known anomalies that must be preserved rather than silently corrected here, including:

- BYE rows;
- multiple QB-classified rows for the same team/game;
- players classified at QB who appear to have started the game at another offensive position (for example Taysom Hill `TE/QB` / `QB/WR` rows);
- occasional odd display-name formatting;
- other rows that cannot safely be accepted as the actual starting quarterback without explicit validation.

No starter is inferred from attempts, passing yards, snaps, fantasy points, result, or other target-game statistics.

## Preservation rule

Files in this directory are raw evidence. Do **not** edit them in place to clean, deduplicate, repair, remap, or resolve starter identity. Any cleaned/reconciled dataset must be written to a **new versioned path** and the existing frozen historical game files must remain unchanged.

## Canonical reconciliation target

The downstream cleaning step must reconcile candidates against the existing canonical 2018-2024 development game universe (1,942 games) and ultimately prove exactly two accepted actual starter assignments per canonical game (3,884 accepted team-game starter assignments) before the dataset can be declared ready.

Calendar dates in January/February 2025 that are postseason games from the **2024 NFL season** remain part of the 2024 development season. The separate **2025 NFL season holdout remains sealed**.

## Chat recovery status

The raw Stathead export was manually copied from the subscriber UI in mobile-browser chunks and pasted into the ChatGPT NFL EDGE working conversation. This directory is the durable repository landing zone so those manual pulls do not have to be repeated.

Because repository writes cannot directly read hidden/skipped chat turns, recovery is being staged with an explicit manifest. A rank is considered safely recovered only when the literal CSV row has been committed here. Coverage summaries from chat are not substituted for missing literal rows.

See `manifest.json` for the recovery/validation contract.
