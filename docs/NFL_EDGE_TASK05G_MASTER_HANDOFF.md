# NFL EDGE — TASK05G MASTER HANDOFF

## Status

**TASK05G COMPLETE PENDING USER MERGE**

Task05G now has a canonical selector + staking + product-policy implementation validated on **2020-2024 only**.

**2025 HAS NOT BEEN OPENED, LOADED, SCORED, REPLAYED, OR RUN FOR TASK05G. IT REMAINS SEALED.**

Do not use 2025 to retune or reinterpret this frozen contract unless a later acceptance phase is explicitly authorized.

---

## Repository / final integration PR

Repository: `Tkcool28/nfl-edge`

Final integration branch:

`feat/task05g-headline-staking-integration-v1`

Final integration PR:

**PR #56 — Task05G: integrate headline staking and rerun canonical 2020-24 product test**

PR #56 is stacked on PR #52. It is not merged by this handoff.

Production-chain PRs relevant to Task05G:

- **PR #50** — final three-lane selector freeze
- **PR #51** — units, five risk profiles, bankroll conversion, Play Through/product simulation infrastructure
- **PR #52** — default-board/game-detail/manual exact-offer product policy
- **PR #56** — final canonical headline staking/actionability integration and final 2020-24 replay

Audit-only development PRs used to test the final behavior:

- **PR #53** — HHR staking audit
- **PR #54** — full 2020-24 product replay audit
- **PR #55** — headline actionability / Value-at rescue audit

Those audit PRs are evidence/experimentation, not the production integration target.

---

# 1. Frozen selectors — unchanged by final staking work

Canonical selector file:

`src/nfl_edge/recommendation/final_selectors_v1.py`

Git blob identity at freeze:

`70985cef2f6d0792ef35364776528403346ec7d2`

The final canonical product replay used these exact selector semantics.

## Hit Rate / HHR

Frozen protocol:

**`HALF_SHRINK`**

- q floor: `.55`
- exact DK/FD offers
- odds band: `[-300, +200]`
- totals excluded
- probability/confidence first
- no EV/status/model-price-gap ranking

ML trust:

`selector_trust = q - 0.5 * max(q - Pinnacle_no_vig, 0)`

Spread trust:

Spread Confidence V3 q passes through as selector trust.

HHR accepted 2020-24 selector evidence:

- 81 selected cards
- 53-27-1
- 66.25% non-push hit rate

## Balanced

Frozen protocol:

**`MARKET_HALF_ONLY`**

- q floor: `.52`
- exact DK/FD offers
- odds band: `[-220, +200]`
- totals excluded
- probability/trust first
- **strict +EV is NOT required**
- no EV/status/model-price-gap ranking

Balanced uses the same market-half trust construction for ML and Spread V3 trust for spread.

Accepted 2020-24 selector evidence:

- 88 selected cards
- 54-34
- 61.36% hit rate
- 80.73% weekly coverage

Balanced may still return no card in a week. The product does not force 100% coverage.

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
- ML requires positive q-vs-break-even/model-price-gap support
- spread uses Expected Margin provenance and positive Spread V3 cover-margin support
- causal family trust / state safety valves retained
- totals excluded

Accepted 2020-24 selector evidence:

- 68 selected cards
- 46-22
- 67.65% hit rate
- 31 ML / 37 spread

The previously observed +43.20% exposed-development flat ROI is **not** a forward expected return and must never be marketed that way.

---

# 2. Final headline staking/actionability

Canonical file:

`src/nfl_edge/recommendation/headline_staking_v1.py`

Git blob identity at freeze:

`5fbc6b688fd939b751f9cefeab9538a8f1159898`

This module is downstream of selection. It must never select, replace, or re-rank headline candidates.

## HHR staking

Once the frozen HHR selector chooses a card, that card is always actionable.

Rules:

- selected HHR headline always shows **BET**
- positive stake is mandatory
- `selector_trust` determines base units
- break-even price pressure may only reduce stake after selection
- price cannot change which HHR candidate was selected
- minimum = `0.25u`
- HHR can never become `NO`, `PASS`, or `0u` solely because the price is heavily juiced
- `HEAVILY_JUICED` warning begins at **+8 percentage points** of break-even pressure relative to HHR selector trust

Base-unit ladder from selector trust:

- `>= .70` → `1.25u`
- `>= .65` → `1.00u`
- `>= .60` → `0.75u`
- otherwise → `0.50u`

Price-pressure haircut:

- `<= 0pp` → no haircut
- `0-4pp` → `-0.25u`
- `4-8pp` → `-0.50u`
- `8-10pp` → `-0.75u`
- `>10pp` → floor at `0.25u`

HHR secondary wording is **Value at X or better**, not Playable Through.

## Balanced staking

Once the frozen Balanced selector chooses a card:

- selected Balanced headline always shows **BET**
- positive stake is mandatory
- preserve a larger canonical generic stake when present
- minimum Balanced headline stake = `0.75u`
- ordinary reduced-price execution extension = **Playable through ...** at `0.50u`

This fixes the old contradiction where an already-selected Balanced headline could show `0u` because generic exact-offer Value/Playable gating was leaking into headline staking.

The selector itself was not loosened to create this behavior.

## Value staking / target-only rescue

If canonical generic staking assigns positive units to a selected Value card:

- show current **BET** with those units
- optional worse-price extension is **Value through X** only while the exact price remains genuinely strict +EV

If a selected strict-Value card is otherwise `0u` because of LOW reliability:

- do not show `BET $0`
- search same-line better American odds
- require at least `1.0pp` improvement in break-even probability
- maximum rescue distance = `1.5pp`
- if reachable, publish **Value at X or better · 0.50u · $Y**
- if not reachable within 1.5pp, suppress the Value headline

In the final exposed 2020-24 replay:

- 40/68 Value cards were current-price BETs
- 28/68 became target-only nearby `Value at` cards
- 0 required suppression
- 0 published headline cards had zero actionable units

Do not infer that future data must also produce zero suppressions. Suppression remains the correct fail-closed behavior if the rescue price is unrealistic.

---

# 3. User-facing wording — final V1

The product wording was deliberately simplified for casual users.

## Primary positive action

Use:

**`BET`**

Do not use `PLAY` as the primary verb.

## Default/game-detail current offer does not qualify

Use:

**`NO`**

Example:

`NO at -125`

`BET at -110 or better · 0.5u · $1.00`

`NO` is an exact-price verdict, not a judgment that the team/game is bad.

Do not use verbose wording like `No recommended stake` on the casual-facing surface.

## HHR example

```text
HHR
Chiefs ML -250
BET · 0.50u · $X
⚠ Heavily juiced      # only when the +8pp rule fires
Value at -220 or better · 1.00u · $Y
```

HHR does **not** use ordinary `Playable through` wording.

## Balanced example

```text
BALANCED
Bears +3 -110
BET · 0.75u · $X
Playable through +2.5 -115 · 0.50u · $Y
```

Any alternate spread/total line must be genuinely reevaluated as an exact offer.

## Value current-price example

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

Do not show a dead `0u` Value headline.

---

# 4. Default rest-of-board / game-detail behavior

Canonical module:

`src/nfl_edge/recommendation/product_policy_v1.py`

Git blob identity at freeze:

`3d0fecc78f5e4a5c8d64cbd473e3513aa18e4441`

All non-headline wager/game-detail recommendations use **Balanced-style policy by default**.

Important distinction:

- weekly Balanced headline = best global Balanced candidate on the board
- game-detail/default path = evaluate the exact market the user selected; do not replace it with another global candidate

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

Manual exact offers must be treated methodologically like sourced DK/FD exact offers.

Rules:

- same frozen Task05F `evaluate_offer`
- same default Balanced policy
- same generic staking
- same risk-profile conversion
- same Playable Through / `BET at` target logic
- same support/reliability requirements
- no manual bonus or discount
- no source-based methodology change

Preserve truthful provenance such as `source=manual`, but source metadata must not alter probability, EV, reliability, support, units, or stake.

Different spread/total lines are new exact offers. No synthetic line conversion is permitted.

---

# 6. Play Through

Play Through is an **execution range on a selected recommendation**, not a second pool of extra bets.

Headline maximum corridor remains:

**1.5 percentage points of break-even probability**

The actual Task05F corridor may be smaller because reliability/uncertainty multipliers still apply.

Use Play Through primarily for Balanced/default actionable price extension.

Do not call a negative-EV Playable Through price `Value`.

---

# 7. Five risk profiles

Canonical staking file:

`src/nfl_edge/recommendation/staking_v1.py`

Git blob identity at freeze:

`eefb5d2585b129c9679b12c5fea1a6c3bdbce88a`

Frozen profiles:

| Profile | 1u bankroll fraction |
|---|---:|
| Cautious | 0.50% |
| Conservative | 0.75% |
| Normal | 1.00% |
| Aggressive | 1.25% |
| Ultra | 1.50% |

Ultra caution:

> Ultra is the highest staking exposure setting. It does not imply higher expected performance, better picks, greater model confidence, or any increase in predictive edge.

Risk profile changes dollars only. It must not alter selector choice, selector ranking, recommended units, probabilities, reliability, or expected edge.

Stake controls:

- minimum dollar stake `$0.50`
- floor rounding to `$0.50`
- per-wager cap `2.5%` bankroll
- slate cap `10%` bankroll
- duplicate exact offer across headline lanes = one actual wager
- if duplicate lanes disagree on units, use the larger recommendation; never add the units
- Kelly prohibited in V1

Canonical conversion accepts `0.25u` solely so the HHR floor can be represented. Generic/default/manual staking was not expanded to recommend 0.25u merely because conversion supports it.

---

# 8. Final canonical 2020-24 validation

Canonical replay workflow:

**Task05G Canonical Product Replay V1**

Run:

`33108088399`

Evidence code head:

`03de639cf4c11f1db1df8e6cfef0a498746007bb`

Artifact:

`9661355282`

Artifact digest:

`sha256:e44b2c1b9ca987200958bebb27e87199dea916fe481eb0bbc8ec6eedfe8b83ef`

Legacy Task05G regression suite also passed:

`33108088294`

The canonical replay explicitly imported no HHR/actionability audit helper.

## Selector identity

- HHR = 81
- Balanced = 88
- Value = 68

No selector drift occurred.

## Headline actionability

- HHR current BET = 81 / 81
- Balanced current BET = 88 / 88
- Value current BET = 40 / 68
- Value target-only `Value at` = 28 / 68
- Value suppressed = 0 in exposed replay
- published headline with zero actionable units = 0

## Follow-every-current-recommendation portfolio

Exact offers deduped; target-only Value-at instructions are not fabricated as historical fills.

Overall 2020-24:

- 174 unique current wagers
- 112 wins / 61 losses / 1 push
- 64.7% non-push hit rate
- 144.00u risked
- +8.05u weighted result

By season:

| Season | Bets | Record | Hit rate | Units | Weighted P/L |
|---|---:|---:|---:|---:|---:|
| 2020 | 17 | 12-5 | 70.6% | 14.00u | +1.73u |
| 2021 | 33 | 18-14-1 | 56.3% | 27.25u | -1.90u |
| 2022 | 41 | 24-17 | 58.5% | 33.00u | +0.28u |
| 2023 | 38 | 23-15 | 60.5% | 31.50u | -2.79u |
| 2024 | 45 | 35-10 | 77.8% | 38.25u | +10.73u |

The season-to-season variability was reviewed and accepted as realistic small-sample NFL variance. Do not try to smooth seasons by retrospective filtering; doing so risks removing the actual model edge and overfitting exposed development data.

## Continuous $1,000 Normal bankroll

- ending bankroll: `$1,075.59`
- return: `+7.56%`
- max drawdown: `8.69%`

These are exposed development results only, not promised forward returns.

---

# 9. Product sanity-check conclusion

The final product has meaningful casual-user coverage without forcing a recommendation every week.

Balanced is not artificially admitting weaker candidates merely to create action. Its 88 selections were already frozen before the staking change. The final staking integration only stopped a downstream Value-oriented gate from showing `0u` beneath an already-selected Balanced headline.

Do not change the selectors to make yearly outcomes smoother.

Do not outcome-tune the 0.75u Balanced floor from the exposed season table.

Do not conflate HHR, Balanced, and Value objectives:

- HHR = highest trustworthy hit probability
- Balanced = best normal probability/price recommendation
- Value = strongest validated strict price edge

---

# 10. Legacy module warning

`src/nfl_edge/recommendation/policy.py` contains older selector/risk-profile code from earlier development.

It remains useful for shared legacy constants/helpers such as no-play sentinels and exact-offer shopping, but **it is not the canonical Task05G selector/staking product contract**.

Canonical production-path sources are:

1. `final_selectors_v1.py`
2. `headline_staking_v1.py`
3. `staking_v1.py`
4. `product_policy_v1.py`

Future integration must not accidentally route production recommendations through the stale selector/risk-profile definitions in `policy.py`.

---

# 11. Freeze manifest

Permanent manifest:

`config/task05g_final_product_freeze_v1.yaml`

Permanent final wording contract:

`docs/task05g_product_output_contract_v1.md`

This handoff:

`docs/NFL_EDGE_TASK05G_MASTER_HANDOFF.md`

---

# 12. Explicit 2025 boundary

Again, for master/project continuation:

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

It remains sealed after this final 2020-24 freeze.
