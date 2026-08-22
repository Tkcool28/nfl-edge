# Task05G — Selector, Unit, Risk Profile, and Play Through Policy V1

## Scope

Task05G is a downstream product-policy layer over the frozen Task05F evaluator contract. It does not retrain or retune ML V4, Spread V3, Total V3, evaluator reliability/uncertainty, Oracle QB-Elo, XGBoost ML, Expected Margin, or Ridge R4.

Development diagnostics are restricted to 2020–2024. Season 2025 remains sealed.

## Concept separation

The policy preserves three distinct axes:

1. **Football confidence** — `actionable_probability`, the underlying football/evaluator probability that the exact wager cashes.
2. **Evaluator reliability** — `reliability`, `uncertainty`, `support_n`, and `support_distance`, describing how trustworthy the accepted evaluator is in this region.
3. **Market quality/value** — exact line/price, `price_status`, `expected_value`, and edge versus break-even.

No composite opaque score is used. A better sportsbook box does not alter football confidence, and football confidence does not make a bad price become Value.

## Exact-offer shopping

Only DraftKings and FanDuel are actionable headline books. Pinnacle remains a benchmark/reference input.

For each game/market/selected side, the policy shops already-evaluated exact offers using:

- Moneyline: better American price.
- Spread: better selected-side number first, then better price.
- Over: lower total first, then better price.
- Under: higher total first, then better price.
- Exact tie: DraftKings before FanDuel, then deterministic candidate identity.

Probability/EV is never transferred from one line or price to another. Every selectable row must be the result for that exact offer.

## Hit Rate selector

Question: **Which supported wager is most likely to cash?**

Eligibility:

- supported evaluator
- reliability HIGH or MEDIUM
- price status VALUE or PLAYABLE
- actionable probability >= 0.55
- American odds between -300 and +200 inclusive
- exact DK/FD offer after shopping

Ranking, in order:

1. actionable probability descending
2. HIGH reliability before MEDIUM
3. VALUE before PLAYABLE
4. expected value descending
5. better American price
6. candidate identity ascending

No qualifying wager returns `NO_HIT_RATE_PLAY`.

## Balanced selector

Question: **Which wager has the best practical combination of probability, price, value, and evaluator reliability?**

Eligibility:

- supported evaluator
- reliability HIGH or MEDIUM
- price status VALUE or PLAYABLE
- actionable probability >= 0.50
- expected value >= -0.03
- American odds between -220 and +200 inclusive
- exact DK/FD offer after shopping

Ranking, in order:

1. VALUE before PLAYABLE
2. HIGH reliability before MEDIUM
3. expected value descending
4. actionable probability descending
5. evaluated edge probability descending
6. candidate identity ascending

No qualifying wager returns `NO_BALANCED_PLAY`.

## Value selector

Question: **Which supported wager offers the strongest legitimate exact-price advantage?**

Eligibility:

- supported evaluator
- reliability HIGH or MEDIUM
- strict Task05F `VALUE` status (therefore EV > 0)
- actionable probability >= 0.35
- American odds between -180 and +250 inclusive
- expected value >= 0.02
- support_n >= 256
- support_distance <= 0.05
- uncertainty <= 0.045
- exact DK/FD offer after shopping

Ranking, in order:

1. expected value descending
2. evaluated edge probability descending
3. HIGH reliability before MEDIUM
4. actionable probability descending
5. candidate identity ascending

No qualifying wager returns `NO_VALUE_PLAY`.

These thresholds are product-safety and interpretability fences, not historical ROI-optimized buckets. Before broad retrospective evaluation, the config preregisters conservative, primary, and permissive Value threshold families. The primary family above is frozen for Task05G; the other families are sensitivity references only and cannot be selected after seeing ROI.

## Longshot guardrail

A headline Value wager must simultaneously satisfy at least 35% actionable probability, price no longer than +250, at least 2% EV, HIGH/MEDIUM reliability, support_n >= 256, support_distance <= 0.05, and uncertainty <= 0.045.

Therefore a +500 wager at approximately 15% win probability is categorically ineligible for headline Value regardless of a small positive evaluator EV.

## Selector overlap

Overlap is allowed. Hit Rate, Balanced, and Value may identify the same exact wager, including all three roles. The policy never forces different picks for UI variety. When dollar exposure is simulated, the same exact offer is counted once rather than tripled.

## Play Through contract

Task05G preserves the frozen Task05F statuses exactly:

- `VALUE`: strictly positive expected value only.
- `PLAYABLE`: supported offer outside strict positive EV but inside the frozen concession corridor.
- `LEAN`: supported preference but current exact price is outside the playable corridor.
- `PASS`: supported/evaluated but not attractive enough for the active path.
- `UNSUPPORTED`: fail closed; never converted to PASS.

The frozen maximum break-even concession is **1.5 percentage points**. Task05F's frozen confidence multiplier may reduce the realized concession below 1.5pp based on reliability/uncertainty; Task05G does not retune it.

For product approval, a displayed "play through" alternate offer is never inferred from a fixed line/price conversion. The exact alternate line, price, side, and market must be normalized and passed through Task05F `evaluate_offer(...)`, then its exact result is classified with the frozen Play Through contract. The old derived threshold field can remain upstream evidence but cannot approve a product offer by itself.

## Unit ladder

Frozen unit ladder:

`0u, 0.5u, 0.75u, 1u, 1.25u, 1.5u`

The unit recommendation is offer quality, not user risk tolerance. Selector role does not change units.

Rules:

- UNSUPPORTED, PASS, LEAN, unsupported row, or reliability outside HIGH/MEDIUM: 0u.
- PLAYABLE: 0.5u; HIGH reliability plus actionable probability >= 0.55: 0.75u. PLAYABLE never exceeds 0.75u.
- VALUE: base 0.75u.
- VALUE with EV >= 0.025 and probability >= 0.50: 1u.
- HIGH-reliability VALUE with EV >= 0.04 and probability >= 0.52: 1.25u.
- HIGH-reliability VALUE with EV >= 0.06, probability >= 0.55, and uncertainty <= 0.025: 1.5u.

This prevents LOW reliability, barely positive EV, and extreme numerical longshot EV from receiving maximum units.

## Risk profiles

Five ordered profiles are frozen:

| Profile | 1 unit |
|---|---:|
| Cautious | 0.50% bankroll |
| Steady | 0.75% bankroll |
| Balanced | 1.00% bankroll |
| Bold | 1.25% bankroll |
| High Gear | 1.50% bankroll |

Risk profile changes dollars only. It does not change selector identity, evaluator output, EV, price status, or recommended units.

## Dollar stake and caps

Formula before caps/rounding:

`bankroll × profile_unit_pct × recommended_units`

Policy:

- per-wager cap: 2.5% of bankroll
- slate cap: 10% of bankroll
- rounding: floor to nearest $0.50, so rounding never increases exposure
- minimum displayed stake: $0.50
- a computed/capped stake below $0.50 becomes $0
- duplicate headline roles for the same exact offer count once toward slate exposure

Kelly sizing is forbidden.

## Full-board and manual-offer compatibility

The `evaluate_policy_offer(...)` adapter accepts the same exact `NormalizedOffer` supplied by a stored box or manual input. It calls frozen Task05F `evaluate_offer(...)`, applies frozen Play Through classification, and then applies the same unit policy. No source-specific staking or selector math exists.

Therefore the same normalized offer and frozen evaluator state produce the same probability, EV/status, and recommended units whether the offer came from DK, FD, a future clicked full-board box, or manual entry.

## Chronological development diagnostics

`scripts/task05g_selector_policy_runner.py` consumes Task05F's historical evaluator board and refuses any season set other than 2020–2024. It selects week/block by week/block and writes:

- `chronological_selector_results.csv`
- `selector_diagnostics.json`
- `coverage_report.json`
- `season_stability_report.json`
- `unit_risk_profile_simulation.json`
- `longshot_behavior.json`
- `artifact_hashes.json`

Selector diagnostics report play counts, no-play weeks, market mix, average price/probability/EV, reliability mix, hit rate, ROI, and pushes. Season stability is reported separately. Value coverage uses the requested 9+/6–8/3–5/0–2 interpretation bands without making them training targets.

Risk-profile simulations use identical selector/unit outputs for all five profiles and report ending bankroll, maximum drawdown, worst losing streak, peak slate exposure, average wager size, and total risked.

## Firewall and scope proof

Task05G CI diffs against base main `4984ea1ee38377f7f5016d2081be8f7c43bda4cd` and fails if the branch changes:

- `src/nfl_edge/value/`
- `src/nfl_edge/models/`
- `src/nfl_edge/backtest/`
- `data/modeling/`
- `data/frozen/`
- Task05D or Task05E frozen evidence

The workflow also verifies both Task05F historical and candidate artifacts contain exactly seasons 2020–2024 before running selectors, runs Task05G twice, byte-compares deterministic artifacts, checks zero Value longshot guardrail violations, and scans Task05G policy scope for environment-secret dependencies.
