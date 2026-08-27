# NFL EDGE — TASK05G MASTER HANDOFF

## Status

**TASK05G COMPLETE PENDING USER MERGE**

Task05G has a canonical selector + staking + product-policy implementation validated on **2020-2024 only**.

**2025 HAS NOT BEEN OPENED, LOADED, SCORED, REPLAYED, OR RUN FOR TASK05G. IT REMAINS SEALED.**

Do not use 2025 to retune or reinterpret this frozen contract unless a later acceptance phase is explicitly authorized.

---

## Repository / final integration PR

Repository: `Tkcool28/nfl-edge`

Final integration branch:

`feat/task05g-headline-staking-integration-v1`

Final integration PR:

**PR #56 — final canonical Task05G product integration/freeze**

PR #56 is stacked on PR #52. It is not merged by this handoff.

Production-chain PRs relevant to Task05G:

- **PR #50** — final three-lane selector freeze
- **PR #51** — units, five risk profiles, bankroll conversion, Play Through/product simulation infrastructure
- **PR #52** — default-board/game-detail/manual exact-offer product policy
- **PR #56** — final canonical headline staking/actionability integration, legacy-policy quarantine, and final 2020-24 replay

Merge order after review:

**#50 → #51 → #52 → #56**

Audit-only development PRs used to test final behavior:

- **PR #53** — HHR staking audit
- **PR #54** — full 2020-24 product replay audit
- **PR #55** — headline actionability / Value-at rescue audit

Those audit PRs are evidence/experimentation and are not production merge targets.

---

# 1. Frozen selectors — unchanged by final staking work

Canonical selector file:

`src/nfl_edge/recommendation/final_selectors_v1.py`

Git blob identity at freeze:

`70985cef2f6d0792ef35364776528403346ec7d2`

## Hit Rate / HHR

Frozen protocol: **`HALF_SHRINK`**

- q floor `.55`
- exact DK/FD offers
- odds `[-300,+200]`
- totals excluded
- no EV/status/model-price-gap ranking

ML trust:

`selector_trust = q - 0.5 * max(q - Pinnacle_no_vig, 0)`

Spread trust: Spread Confidence V3 q passes through as selector trust.

Accepted 2020-24 selector evidence:

- 81 selected cards
- 53-27-1
- 66.25% non-push hit

## Balanced

Frozen protocol: **`MARKET_HALF_ONLY`**

- q floor `.52`
- exact DK/FD offers
- odds `[-220,+200]`
- totals excluded
- probability/trust first
- **strict +EV is NOT required**
- no EV/status/model-price-gap ranking

Accepted 2020-24 selector evidence:

- 88 selected cards
- 54-34
- 61.36% hit
- 80.73% weekly coverage

Balanced may still return no card. Coverage is not forced to 100%.

## Value

Value remains the only strict +EV headline lane.

Frozen validated families:

Moneyline:

- `ML_DOG_VALUE_ZONE_AVG`
- `ML_DOG_VALUE_ZONE_CORROB`
- `ML_AVG_DISAGREEMENT_AVG_0_2`

Spread:

- `SPREAD_DISAGREEMENT_EXPECTED_MARGIN_0_4`

Core rules:

- strict positive EV
- exact DK/FD offer
- model support >=256
- `price_status=VALUE`
- odds `[-180,+250]`
- ML positive q-vs-break-even/model-price-gap support
- spread Expected Margin provenance + positive Spread V3 cover-margin support
- causal family trust/state safety valves retained
- totals excluded

Accepted 2020-24 selector evidence:

- 68 selected cards
- 46-22
- 67.65% hit
- 31 ML / 37 spread

The exposed-development +43.20% flat ROI is **not** a forward expected return and must never be marketed as such.

---

# 2. Final headline staking/actionability

Canonical file:

`src/nfl_edge/recommendation/headline_staking_v1.py`

Git blob identity:

`5fbc6b688fd939b751f9cefeab9538a8f1159898`

This module is downstream of selection and must never select/re-rank candidates.

## HHR

Once HHR selects a card:

- always **BET**
- positive stake mandatory
- `selector_trust` determines base units
- price pressure may only reduce stake after selection
- price cannot change the HHR candidate
- minimum `0.25u`
- never `NO`/`PASS`/`0u` solely because of juice
- `HEAVILY_JUICED` warning begins at +8pp BE pressure relative to selector trust

Base units:

- >=.70 → 1.25u
- >=.65 → 1.00u
- >=.60 → 0.75u
- otherwise → 0.50u

Price-pressure haircut:

- <=0pp: none
- 0–4pp: -0.25u
- 4–8pp: -0.50u
- 8–10pp: -0.75u
- >10pp: floor 0.25u

Secondary wording: **Value at X or better**.

## Balanced

Once Balanced selects a card:

- always **BET**
- preserve any larger canonical generic stake
- minimum headline stake `0.75u`
- reduced execution extension: **Playable through ...** at `0.50u`

This fixed the prior contradiction where the selector chose a Balanced headline but generic Value/Playable staking could display 0u. The selector itself was not loosened.

## Value

If canonical generic staking gives positive units:

- current **BET**
- optional worse-price extension: **Value through X**, only while still strict +EV

If selected strict Value is otherwise 0u because of LOW reliability:

- never show `BET $0`
- search same-line better American odds
- require >=1.0pp BE improvement
- cap rescue distance at <=1.5pp
- target recommendation `0.50u`
- wording **Value at X or better**
- suppress headline if no realistic rescue exists

Final exposed replay:

- 40 current Value BETs
- 28 target-only nearby Value-at cards
- 0 suppressed
- 0 published dead-0u headline cards

Future suppression remains valid fail-closed behavior if a realistic rescue price does not exist.

---

# 3. User-facing wording — final V1

Primary positive action: **`BET`**.

Do **not** use `PLAY` as the primary recommendation verb.

Default/game-detail current exact offer that does not qualify: **`NO`**.

Example:

```text
NO at -125
BET at -110 or better · 0.5u · $1.00
```

`NO` is an exact-price verdict, not a judgment that the team/game is bad.

## HHR example

```text
HHR
Chiefs ML -250
BET · 0.50u · $X
⚠ Heavily juiced      # only when +8pp rule fires
Value at -220 or better · 1.00u · $Y
```

HHR does not use ordinary Playable Through wording.

## Balanced example

```text
BALANCED
Bears +3 -110
BET · 0.75u · $X
Playable through +2.5 -115 · 0.50u · $Y
```

Any alternate spread/total line must be genuinely reevaluated.

## Value current example

```text
VALUE
Bears ML +145
BET · 1.00u · $X
Value through +137 · 0.75u · $Y
```

`Value through` must remain strict +EV.

## Value target-only example

```text
VALUE
Bears ML +145
Value at +152 or better · 0.50u · $X
```

Do not show a dead 0u Value headline.

---

# 4. Default rest-of-board / game-detail

Canonical module:

`src/nfl_edge/recommendation/product_policy_v1.py`

Git blob:

`3d0fecc78f5e4a5c8d64cbd473e3513aa18e4441`

All non-headline/game-detail recommendations use Balanced-style policy by default.

- weekly Balanced headline = best global Balanced candidate
- game-detail/default = evaluate the exact user-selected market locally; never replace it with another global candidate

Qualifying current offer:

```text
BET at -110 · 1.0u · $2.50
Playable through -118 · 0.5u · $1.00
```

Nonqualifying current offer:

```text
NO at -125
BET at -110 or better · 0.5u · $1.00
```

---

# 5. Manual entries

Manual exact offers are methodologically identical to sourced DK/FD exact offers:

- same Task05F `evaluate_offer`
- same default Balanced policy
- same generic staking
- same risk-profile conversion
- same Playable Through / BET-at target logic
- same support/reliability rules
- no manual bonus/discount

Keep `source=manual` truthful as provenance only. It must not alter probability, EV, reliability, support, units, or stake.

Different spread/total lines are new exact offers. Synthetic line conversion is prohibited.

---

# 6. Play Through

Play Through is an **execution range on a selected recommendation**, not a second pool of bets.

Maximum headline corridor remains **1.5 percentage points of break-even probability**; the actual Task05F corridor may be smaller because reliability/uncertainty multipliers apply.

Use it primarily for Balanced/default actionable price extension. Never label a negative-EV Playable Through price as Value.

---

# 7. Five risk profiles

Canonical staking:

`src/nfl_edge/recommendation/staking_v1.py`

Git blob:

`eefb5d2585b129c9679b12c5fea1a6c3bdbce88a`

| Profile | 1u bankroll fraction |
|---|---:|
| Cautious | 0.50% |
| Conservative | 0.75% |
| Normal | 1.00% |
| Aggressive | 1.25% |
| Ultra | 1.50% |

Ultra caution:

> Ultra is the highest staking exposure setting. It does not imply higher expected performance, better picks, greater model confidence, or any increase in predictive edge.

Risk profile changes dollars only, not candidate, ranking, units, probability, reliability, or expected edge.

Controls:

- minimum dollar stake $0.50
- floor rounding to $0.50
- per-wager cap 2.5% bankroll
- slate cap 10%
- duplicate exact offer across lanes = one actual wager
- disagreement on duplicate units → use larger recommendation, never add
- Kelly prohibited V1
- 0.25u conversion support exists only for HHR floor; generic/default/manual staking was not expanded to 0.25u

---

# 8. Cold-review blocker — REMEDIATED

A fresh independent review correctly identified a merge blocker: the historical `src/nfl_edge/recommendation/policy.py` still exposed live callable pre-final Task05G selectors, old risk profiles, and old staking behavior at a plausible import path.

That architecture was not acceptable because callers could import stale semantics directly even though documentation said not to.

## Final remediation

`policy.py` is now intentionally **shared-helper / compatibility-adapter only**.

Current Git blob:

`d72cea40119425ca9c877428654bb52c34799bc5`

It retains only genuinely shared surfaces such as:

- `NO_HIT_RATE_PLAY`
- `NO_BALANCED_PLAY`
- `NO_VALUE_PLAY`
- exact DK/FD `shop_exact_offers`
- `PolicyEvaluation`
- `evaluate_policy_offer`

`evaluate_policy_offer()` delegates unit sizing to canonical `staking_v1.recommended_units`; it does not own another staking policy.

It no longer exposes competing:

- `select_hit_rate`
- `select_balanced`
- `select_value`
- `select_headlines`
- `recommended_units`
- `dollar_stake`
- `cap_slate_stakes`
- legacy `RiskProfile` / `RISK_PROFILES` / old profile names

Regression guard:

`tests/recommendation/test_task05g_policy_legacy_quarantine_v1.py`

This verifies both that stale APIs are absent from `nfl_edge.recommendation.policy` and that package-level `nfl_edge.recommendation` exports point to the canonical V1 selector/staking modules.

The old `tests/recommendation/test_task05g_policy.py` was also rewritten so it no longer enforces obsolete APIs.

## Historical preregistration reproducibility

Some preregistered Model Confidence V2 / Spread Confidence V3 experiment runners historically compared against the old pre-final selector baseline. Those baseline semantics are still needed to reproduce those old experiment comparisons, but they are **not production APIs**.

They are now isolated as explicitly named runner-local `_legacy_v1_select_*` functions inside:

`scripts/task05g_model_confidence_v2_runner.py`

Spread V3 references those runner-local historical functions rather than `policy.py`.

The post-remediation product workflow successfully reproduced both Model Confidence V2 and Spread Confidence V3, proving the old experiment evidence remains reproducible while the production import path is fail-closed.

---

# 9. Final post-remediation 2020-24 validation

Permanent-tree validation head before this handoff/manifest documentation update:

`c4533845d815d2481c305b1fdc82693bcf31662f`

All three required workflows passed:

1. **Task05G Final Product Freeze V1** — run `33119361164` — SUCCESS
2. **Task05G Canonical Product Replay V1** — run `33119361132` — SUCCESS
3. **Task05G Product Simulation V1** — run `33119361166` — SUCCESS

Canonical replay artifact:

- artifact `9665847701`
- digest `sha256:7c14dd19e6cc98cc5559871a68c2b77d091979feaa88efe794bb78c2208a7316`

The product suite explicitly passed:

- recommendation/default/manual/selector tests
- Task05F evaluator + Play Through tests
- 2025 firewall
- Model Confidence V2 reproduction
- Spread Confidence V3 reproduction
- deterministic 2020-24 simulation
- product invariants

## Selector identity

- HHR 81
- Balanced 88
- Value 68

No selector drift occurred.

## Headline actionability

- HHR current BET: 81/81
- Balanced current BET: 88/88
- Value current BET: 40/68
- Value target-only `Value at`: 28/68
- Value suppressed: 0 in exposed replay
- published headline with zero actionable units: 0

## Follow-every-current-recommendation portfolio

Exact offers deduped; target-only Value-at instructions are not fabricated historical fills.

Overall 2020-24:

- 174 unique current wagers
- 112-61-1
- 64.7% non-push hit
- 144.00u risked
- +8.05u weighted result

| Season | Bets | Record | Hit rate | Units | Weighted P/L |
|---|---:|---:|---:|---:|---:|
| 2020 | 17 | 12-5 | 70.6% | 14.00u | +1.73u |
| 2021 | 33 | 18-14-1 | 56.3% | 27.25u | -1.90u |
| 2022 | 41 | 24-17 | 58.5% | 33.00u | +0.28u |
| 2023 | 38 | 23-15 | 60.5% | 31.50u | -2.79u |
| 2024 | 45 | 35-10 | 77.8% | 38.25u | +10.73u |

Season-to-season variability was reviewed and accepted as realistic small-sample NFL variance. Do not smooth it via retrospective filters.

Normal continuous $1,000 bankroll:

- ending $1,075.59
- +7.56%
- max drawdown 8.69%

These are exposed development results, not promised forward returns.

---

# 10. Product sanity-check conclusion

The final product has meaningful casual-user coverage without forcing action every week.

Balanced's 88 selections were already frozen before the staking correction. The actionability fix did not admit weaker candidates; it removed a downstream contradiction that could show 0u under an already-selected Balanced headline.

Do not change selectors to smooth yearly outcomes or outcome-tune the 0.75u Balanced floor from exposed season results.

Keep lane objectives distinct:

- HHR = highest trustworthy hit probability
- Balanced = best normal probability/price recommendation
- Value = strongest validated strict price edge

---

# 11. Freeze manifest / canonical sources

Permanent freeze manifest:

`config/task05g_final_product_freeze_v1.yaml`

Permanent wording contract:

`docs/task05g_product_output_contract_v1.md`

This handoff:

`docs/NFL_EDGE_TASK05G_MASTER_HANDOFF.md`

Canonical production-path sources:

1. `src/nfl_edge/recommendation/final_selectors_v1.py`
2. `src/nfl_edge/recommendation/headline_staking_v1.py`
3. `src/nfl_edge/recommendation/staking_v1.py`
4. `src/nfl_edge/recommendation/product_policy_v1.py`
5. `src/nfl_edge/recommendation/policy.py` — shared helpers/adapter only; no competing policy implementation

---

# 12. Explicit 2025 boundary

## **2025 HAS NOT BEEN RUN.**

For Task05G, 2025 was not:

- opened
- loaded
- scored
- replayed
- used for selector tuning
- used for staking tuning
- used for Value-at threshold tuning
- used for product acceptance

It remains sealed after the final 2020-24 freeze and after the cold-review remediation.
