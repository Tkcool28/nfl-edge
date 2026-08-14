# Task 05C — Totals V1 Feature Production-Parity Assessment

For every CORE_V1 family, answers: *Can NFL EDGE reasonably obtain the same
information before kickoff during the live 2026+ pipeline?*

## Assessment labels

| Status | Meaning |
|---|---|
| READY_EXISTING_PIPELINE | Already available from accepted promoted/production pipeline sources with no adapter needed |
| REQUIRES_LIVE_SOURCE_ADAPTER | Source exists but a live pregame adapter/connector must be written |
| REQUIRES_SCHEDULE_REFRESH | Schedule data must be refreshed before each season |
| RESEARCH_ONLY_NOT_PRODUCTION_PARITY | No live production source planned or feasible |

## Per-family assessment

### L — Rest/scheduling
**READY_EXISTING_PIPELINE.** Schedules are refreshed before each season.
Rest gaps are derived from schedule dates, which are available pregame.

### K — Game environment (roof, surface)
**READY_EXISTING_PIPELINE.** Roof and surface are seasonal venue constants
determinable from the schedule's venue mapping before kickoff. No live
weather feed is required (realized weather is REJECTED per contract).

### M — Quarterback context (Oracle QB v2)
**REQUIRES_LIVE_SOURCE_ADAPTER.** The accepted Oracle QB entering-state v2
builder already exists in the production pipeline and runs on eligible prior
games. It does not require PBP; it consumes game-level QB stats and prior
states. The facing adapter (mapping game_id + side to eligible historical
nflverse QB stats) needs a scheduled feed refresh each week, but the builder
code is already production-capable. The existing pipeline's QB state builder
has an adapter gap: the pregame Oracle builder currently runs from historical
frozen nflverse QB stats; a self-feeding live pipeline needs the same
nflverse weekly QB snapshot fetched fresh each Tuesday. The Oracle interface
**does not use PBP** for QB state — it uses nflverse game-level QB stats,
which are available weekly.

### A/B — Offensive/defensive efficiency (EPA/play, success rate, points/drive, scoring-drive rate)
**REQUIRES_LIVE_SOURCE_ADAPTER.** These metrics require live refreshed PBP
for the eligible prior game universe. The existing nflverse PBP promotion
pipeline already exists (`/var/lib/chatgpt-vps-mcp/artifacts/nfl-edge/raw/`).
The gap: a scheduled weekly nflverse PBP fetch for all prior completed games
is needed before each week's prediction run. The accepted Totals V1 builder
already reads from the PBP root path. Once PBP is refreshed weekly, this is
READY. No adapter rewrite needed in the feature builder — only the PBP
refresh automation.

### C — Pace / play volume
**REQUIRES_LIVE_SOURCE_ADAPTER.** Same PBP refresh dependency as A/B above.
The builder's clock-pair logic is source-agnostic once PBP is available.

### D — Passing environment
**REQUIRES_LIVE_SOURCE_ADAPTER.** Same PBP refresh dependency. Neutral pass
rate, air yards/attempt, YAC/completion all derive from the VFP population.

### E — Rushing environment (explosive rush)
**REQUIRES_LIVE_SOURCE_ADAPTER.** Same PBP refresh dependency.

### F — Explosive-play environment (explosive pass + rush rates)
**REQUIRES_LIVE_SOURCE_ADAPTER.** Same PBP refresh dependency.

### G — Red-zone / finishing drives
**REQUIRES_LIVE_SOURCE_ADAPTER.** Red-zone & goal-to-go TD rates derive from
PBP; same refresh dependency.

### H — Turnover environment
**REQUIRES_LIVE_SOURCE_ADAPTER.** Turnovers/drive from PBP; same refresh
dependency.

### I — Pressure / sacks
**REQUIRES_LIVE_SOURCE_ADAPTER.** Sacks/dropback from PBP; same refresh
dependency.

## Production-parity summary

| Family | Parity status | Action needed for 2026+ |
|---|---|---|
| Rest/scheduling (L) | READY_EXISTING_PIPELINE | None |
| Game environment (K) | READY_EXISTING_PIPELINE | None |
| QB context (M) | REQUIRES_LIVE_SOURCE_ADAPTER | Weekly nflverse QB stats refresh + adapter |
| All PBP-derived families (A/B, C, D, E, F, G, H, I) | REQUIRES_LIVE_SOURCE_ADAPTER | Weekly nflverse PBP refresh for completed games |

## Note

Current injuries/depth and realized historical weather/temperature remain
governed by Phase-2 DEFER/REJECT decisions. No production parity gap exists
for rejected families because no production implementation is planned.

This assessment does not change CORE_V1 semantics. It identifies the adapter
work needed for live 2026+ production parity, primarily automated weekly
nflverse PBP and QB-stats refresh.