# Task05G ML Value Dynamic Trust V1 Review

Verdict: `DYNAMIC_TRUST_PARTIALLY_LIMITS_2023_DAMAGE_BUT_FALSE_ALARMS_ON_BROAD_POOL`

This was a preregistered retrospective diagnostic. No Task05F evaluator, football model, production selector policy, Task05E evidence, historical data, or sealed 2025 data was changed.

Evidence:
- preregistration commit `151d2799044b94dd1b29f0aac31bb74af81634c8`
- preregistration blob `6b8425daeef87dc8f7d4b9dc995cc2a19263fe1a`
- implementation/workflow head `e8862d79dd46e03a1f2e5c11b389e3604ea7f9f5`
- workflow `32812790044` — SUCCESS
- artifact `9550400456`
- artifact digest `sha256:26e869de780f8bd48430afa3c6d00979570460771435a437c9d10175ec38bb4c`
- deterministic replay PASS
- 2025 sealed

## Frozen variants

- D0: frozen Value V2 baseline.
- D1: ML model-price gap multiplied by causal same-season trust for ranking only.
- D2: D1 plus RED gate when trust < 0.25 after >= 8 prior same-season ML Value opportunity observations.
- season reset trust 0.50, pseudo-count 8.

The trust observation stream intentionally used **all** unique strict-Value ML opportunities after exact shopping, not only selected headlines.

## 2020–2022 development replay

| Variant | Plays | ROI | ML plays / ROI | Spread plays / ROI |
|---|---:|---:|---:|---:|
| D0 | 50 | +32.91% | 40 / +41.86% | 10 / -2.86% |
| D1 | 50 | +19.30% | 33 / +22.09% | 17 / +13.89% |
| D2 | 46 | +21.20% | 23 / +33.12% | 23 / +9.27% |

D2 retained 92% of D0 play count and did not trip the preregistered coverage-collapse guard.

However, D2 falsely suppressed a genuinely profitable 2022 ML headline stream:

- D0 2022 ML: 16 plays, +36.35% ROI.
- D2 2022 ML: 1 play.
- trust fell below 0.50 in Week 4 and below 0.25 in Week 5.

The broad all-opportunity trust pool finished 2022 with predicted-edge sum +7.64 but realized-edge sum -4.27, even though the **selected** ML headline stream was strongly profitable. This proves the broad eligible pool is not an appropriate proxy for the selector's ML decision frontier.

## 2023–2024 exposed stress replay

| Variant | Plays | ROI | ML plays / ROI | Spread plays / ROI |
|---|---:|---:|---:|---:|
| D0 | 39 | -24.29% | 18 / -58.12% | 21 / +4.71% |
| D1 | 39 | -22.87% | 17 / -52.39% | 22 / -0.05% |
| D2 | 35 | -8.28% | 7 / -10.10% | 28 / -7.83% |

D2 retained 89.7% of D0 plays, reduced max losing streak from 8 to 4, and materially reduced ML exposure after deterioration.

### 2023 specifically

- D0: 19 plays, -54.31% ROI; ML 12 plays, -85.0% ROI.
- D2: 15 plays, -28.67% ROI; ML 1 play, -100% ROI.
- trust fell below 0.50 in Week 5 (7 prior observations) and below 0.25 in Week 6 (10 observations).

Thus the dynamic gate did detect the severe 2023 deterioration causally and limited later ML damage.

### 2024

- D0: +4.23% ROI.
- D2: +7.00% ROI.
- trust fell below 0.50 in Week 6, below 0.25 in Week 10, then later recovered above RED; final same-season trust was ~0.596.

## Root cause of V1 trust failure

The trust signal watched the wrong population.

Using every eligible ML Value opportunity makes trust sensitive to many lower-ranked candidates that would never become the weekly Value headline. In 2022 that broad pool looked unprofitable and triggered RED even while the actual selected ML stream was profitable.

Therefore V1 establishes two points:

1. **Adaptive same-season trust can materially limit a genuinely collapsing ML edge without destroying overall play coverage.**
2. **Trust must be measured on a population aligned with the selector's decision frontier, not the full eligible ML pool.**

## Next diagnostic design

A follow-up should preserve all V1 constants and change only the trust observation stream:

- identify the single highest-ranked ML Value candidate in each block using the frozen V2 Value ranking restricted to ML;
- after that block settles, add only that counterfactual/top-ML candidate to future trust state;
- use the same 0.50 season reset, pseudo-count 8, ranking shrink, 0.25 RED gate, and coverage guard;
- compare whether this frontier-aligned trust stays appropriately confident in profitable 2022 while still checking itself during the 2023 collapse.

Because 2023–2024 are already exposed, any follow-up remains retrospective stress analysis, not fresh confirmation. 2025 remains sealed.