# Task05G Final Selector Freeze V1

## Status

`FINAL_THREE_LANE_SELECTOR_DEVELOPMENT_FREEZE_2025_SEALED`

Canonical selector semantics are frozen at commit:

`f1611bd42475bf05c49188e07dfb494e5e1ce86e`

Canonical source:

- `src/nfl_edge/recommendation/final_selectors_v1.py`
- `config/task05g_final_selectors_v1.yaml`
- `scripts/task05g_final_selectors_freeze_v1.py`
- `tests/recommendation/test_task05g_final_selectors_v1.py`

Package-level recommendation selector exports now resolve to the canonical V1 selector module. Legacy selector functions remain in `policy.py` only for historical comparison; they are not the canonical Task05G selector contract.

## Frozen lane semantics

### Hit Rate — HALF_SHRINK

Question: **which supported wager has the highest trustworthy chance to cash?**

- model-confidence probability floor: 0.55
- exact DraftKings/FanDuel offer
- odds band: -300 to +200
- ML trust: `q - 0.50 * max(q - Pinnacle_no_vig, 0)`
- spread trust: Spread Confidence V3 probability
- primary rank: selector trust, then model confidence
- EV, price status, and model-price gap are not eligibility/ranking objectives
- no totals headline

### Balanced — MARKET_HALF_ONLY

Question: **which supported wager gives the best probability-first choice at a reasonable actual price?**

- model-confidence probability floor: 0.52
- exact DraftKings/FanDuel offer
- odds band: -220 to +200
- same market-half ML trust; spread uses Spread Confidence V3 probability
- probability/trust first; EV and market status cannot turn it into Value Lite
- no totals headline

### Value — strict +EV with family trust and fail-closed safeguards

Common:

- exact DraftKings/FanDuel offer
- strict `price_status == VALUE`
- strict `expected_value > 0`
- odds band: -180 to +250
- supported/model-confidence-supported provenance
- no totals headline in V1

Frozen ML provenance:

- `ML_DOG_VALUE_ZONE_AVG`
- `ML_DOG_VALUE_ZONE_CORROB`
- `ML_AVG_DISAGREEMENT_AVG_0_2`

Frozen spread provenance:

- `SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4`

Spread frontier:

- Pareto/maximin consensus of model-strength rank and Task05F economic rank
- no unrestricted max raw Expected-Margin or max-EV frontier

Causal family trust constants:

- reset trust = 0.50
- pseudo-count = 8
- AMBER at `n >= 3` and trust `< 0.50`
- RED at `n >= 8` and trust `< 0.25`
- state resets by season
- each family updates from its own strictly-prior settled deterministic frontier

Spread safety valve:

- AMBER/RED spread family
- exactly one strict spread candidate
- => `NO_VALUE_PLAY`
- no backfill

ML safety valve:

- COLD (`n < 3`) or AMBER ML evidence
- exactly one strict ML candidate
- no valid Pareto spread frontier
- => `NO_VALUE_PLAY`
- no backfill

Mature singleton ML remains eligible. Competitive Pareto spread remains eligible even in degraded spread state. ML RED remains barred by the existing causal family policy.

## Integrated development replay

Validated workflow:

- run: `33045100544`
- artifact: `9635344273`
- artifact digest: `sha256:e15021346f3062049c64e8e19c0c63da0ea41ab2df0a9af70d6dfed65779e95c`

The workflow rebuilt Task05F, Model Confidence V2, and Spread Confidence V3, enforced the 2025 firewall, ran the canonical selector tests, replayed all selectors twice, and proved byte-identical outputs.

### 2020–2024 overall

| Lane | Plays | Coverage | Record | Non-push hit rate | Flat ROI (secondary) |
|---|---:|---:|---:|---:|---:|
| Hit Rate | 81 | 74.31% | 53-27-1 | 66.25% | -2.75% |
| Balanced | 88 | 80.73% | 54-34 | 61.36% | -1.89% |
| Value | 68 | 62.39% | 46-22 | 67.65% | +43.20% |

Value ROI is exposed development evidence and is **not** a forward-return expectation.

### Value safety-year check

2023 final Value:

- 7 plays
- 3-4
- -1.305 flat units
- -18.65% ROI

2024 final Value:

- 14 plays
- 11-3
- +6.725 flat units

The safety design intentionally contains the exposed 2023 failure without forcing 2023 to become profitable.

## Implementation-defect record

The first canonical replay incorrectly added a HIGH/MEDIUM reliability eligibility gate that was not part of the accepted selector research. It reduced HHR/Balanced/Value volume and failed to reproduce the accepted evidence.

That was treated as an implementation defect, not a selector redesign. The unintended gate was removed before the corrected semantic freeze. Task05F `supported` and model-confidence support remain the common support gates; reliability remains a deterministic ranking/tie-break signal where specified.

A separate test-fixture defect was also corrected: at eight zero-trust observations the frozen pseudo-count formula yields trust exactly 0.25, while RED is strictly `< 0.25`; the RED fixture therefore uses nine observations.

Neither correction used 2025 or introduced a new performance threshold.

## Freeze rule

After `f1611bd42475bf05c49188e07dfb494e5e1ce86e`:

- no selector threshold tuning from 2020–2024 results;
- no new selector family or ranking formula;
- no 2025 access;
- implementation/test/report corrections are allowed only when they restore the frozen contract rather than alter it.

The next Task05G work is downstream recommendation policy: units, five risk profiles, unit-to-dollar conversion/caps, Play Through behavior, and the 2020–2024 product simulation. Those layers must consume this selector contract rather than alter it.
