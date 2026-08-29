# NFL EDGE — Pre-2025 Holdout Acceptance Specification V1

## Status

Frozen before opening the 2025 holdout. This document defines what the eventual one-shot 2025 simulated-live acceptance run must report and how it may be interpreted. It does not authorize opening 2025.

## Core acceptance question

If an ordinary NFL bettor had opened NFL EDGE every week in 2025, would the app have produced a useful, honest, understandable card under the already-frozen Task05F/Task05G methodology?

## Required chronology

The run is chronological by NFL season/week block. For every block, all pregame football predictions, market evaluations, confidence/trust values, headline selections, actionability, recommended units, profile dollar stakes, Play Through guidance, Value-at guidance, and full-board outputs must be frozen before that block's outcomes are admitted to any later state.

No current-block or future-block outcome may influence a pregame recommendation. No retroactive knowledge is permitted.

## Headline usefulness metrics

Report, at minimum:

- Hit Rate selections and no-play weeks
- Balanced selections and no-play weeks
- Value current bets, target-only cards, suppressed cards, and no-play behavior
- selector overlap and duplicate exact offers
- market mix and price distribution
- headline coverage versus full-board coverage

No lane is required to force a play.

## Prediction / support metrics

Report, at minimum:

- per-lane and per-market W/L/P and non-push hit rate
- average offered odds
- model-confidence / trust distribution where applicable
- support/reliability distribution
- unsupported and fail-closed counts
- calibration diagnostics where the frozen methodology already defines them

Unsupported rows must remain unsupported and cannot be promoted to create coverage.

## Betting / bankroll metrics

Report, at minimum:

- exact actionable DraftKings/FanDuel offer chosen
- Pinnacle benchmark attached to the same market state
- recommended units
- dollar stake for all five frozen risk profiles
- duplicate exact-offer handling
- per-wager cap and slate-cap enforcement
- flat-unit profit
- recommended/weighted-unit profit
- profile bankroll trajectory
- ending bankroll
- maximum drawdown
- longest losing streak
- total exposure

A duplicate exact offer surfaced by multiple headline lanes is one wager, with the maximum applicable frozen unit recommendation rather than additive staking.

## Product honesty metrics

The report must explicitly count and expose:

- forced-action weeks
- published zero-dollar / zero-actionable-unit headlines
- unsupported promoted recommendations
- negative-EV wagers mislabeled as Value
- target prices treated as if filled
- synthetic or fake line conversions
- duplicate wagers double-counted
- full-board coherence failures

`VALUE` remains strict positive evaluated EV. `PLAYABLE` remains a bounded Play Through concession state and must not be marketed as Value.

## Acceptance dimensions

The 2025 result is evaluated across four separate dimensions:

1. implementation integrity
2. probability / selector behavior
3. wagering-result variance and bankroll behavior
4. product usefulness / honesty

There is no single arbitrary ROI hurdle that automatically determines acceptance.

A profitable 2025 season does not prove durable edge. A losing 2025 season does not by itself prove an implementation defect. The purpose of the holdout is an untouched final product acceptance test, not a new tuning set.

## Prohibited interpretation

After 2025 is opened, do not change any of the following because of the observed result:

- evaluator formulas or thresholds
- support / reliability rules
- trust / confidence formulas or thresholds
- selector thresholds, odds bands, families, or ranking logic
- unit ladders
- risk profiles
- wager/slate caps
- Play Through concession corridor
- Value-at / Value-through semantics
- market/model families
- season/team filters
- new retrospective buckets or rescue filters

## Implementation-defect exception

A methodology-preserving implementation defect may be repaired only if:

- the defect is documented precisely
- the original failed 2025 artifact is preserved unchanged
- the repair is shown not to change intended methodology
- a new versioned freeze is created before rerun
- the rerun is labeled transparently as a defect-correction rerun

## Required final artifacts

The one-shot runner must emit a complete, unomitted artifact set including:

- holdout headline cards
- weekly summary
- lane summary
- market mix
- bankroll scenarios
- scenario ledger
- product-integrity report
- provenance report
- final acceptance report
- deterministic hashes for all permanent outputs

The full-game market board remains part of the product. Headline picks are only a summary layer.

## Stop rule

This specification is frozen during pre-holdout preparation. The 2025 holdout must remain sealed until the prefreeze audit is complete and Master explicitly authorizes the one-shot spend.
