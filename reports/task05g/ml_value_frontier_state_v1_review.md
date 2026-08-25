# Task05G ML Value Frontier State V1 Review

Verdict: `FRONTIER_STATE_MATERIALLY_LIMITS_2023_ML_DAMAGE_BUT_CANNOT_OVERCOME_SPREAD_REPLACEMENT_RISK`

This was a preregistered retrospective diagnostic. No Task05F evaluator, football model, production selector policy, Task05E evidence, historical data, or sealed 2025 data was changed.

Evidence:
- preregistration commit `73de12dd34ef97fe445cb29300c2b85a5e48c37e`
- preregistration blob `5844dc8d62c0e9504bf3ee2719862cdd97a3f383`
- implementation/workflow head `425eb42fd5cd5ef1492824637817197207f99c9e`
- workflow `32813348073` — SUCCESS
- artifact `9550585379`
- digest `sha256:b5a06862e6f2156a02a5e29faa8abfffff67547dd7bebd6801deb40473320e93`
- deterministic replay PASS
- 2025 sealed

## Frozen states

- GREEN: fewer than 3 frontier observations or trust >=0.50; normal frontier dynamic ranking.
- AMBER: >=3 observations and trust <0.50 but RED inactive; a valid spread Value candidate outranks ML, otherwise ML may still play.
- RED: >=8 observations and trust <0.25; ML barred from headline, spread may replace it, otherwise PASS.

No state thresholds were changed after results.

## 2020–2022 development replay

| Variant | Plays | ROI | ML plays / ROI | Spread plays / ROI |
|---|---:|---:|---:|---:|
| S0 baseline | 50 | +32.91% | 40 / +41.86% | 10 / -2.86% |
| S1 frontier shrink | 50 | +33.19% | 37 / +43.30% | 13 / +4.43% |
| S2 GREEN/AMBER/RED | 50 | +32.81% | 36 / +41.44% | 14 / +10.60% |

S2 preserved 100% of development play count and essentially all baseline development ROI.

### 2022

- S0: 19 plays, +35.39% ROI; ML 16 at +36.35%.
- S2: 19 plays, +37.17% ROI; ML 14 at +30.65%; spread 5 at +55.41%.

The state machine did **not** repeat the broad-pool false alarm. It preserved the profitable 2022 season while modestly shifting two ML headlines.

## Exposed 2023–2024 stress replay

| Variant | Plays | ROI | ML plays / ROI | Spread plays / ROI |
|---|---:|---:|---:|---:|
| S0 baseline | 39 | -24.29% | 18 / -58.12% | 21 / +4.71% |
| S1 frontier shrink | 39 | -22.87% | 17 / -52.39% | 22 / -0.05% |
| S2 state machine | 37 | -18.84% | 8 / -47.25% | 29 / -11.01% |

S2 retained 94.9% of baseline play count. Coverage did not collapse.

## 2023

- S0: 19 plays, -54.31%; ML 12 at -85.0%.
- S2: 18 plays, -30.56%; ML 4 at -55.0%; spread 14 at -23.57%.
- first AMBER: Week 6, after 3 prior frontier observations, trust 0.364.
- first RED: Week 12, after 9 observations, trust 0.235.
- state blocks: 5 GREEN / 6 AMBER / 11 RED.
- AMBER displaced 2 ML headlines to spread; RED created 4 no-play blocks.

The early AMBER response materially reduced the 2023 catastrophe and cut the max losing streak from 8 to 4. This validates the idea that the system can start a season with partial trust and check itself causally as evidence arrives.

However, replacement spreads were themselves poor in 2023, so the guardrail could not turn the card positive.

## 2024

- S0: 20 plays, +4.23%.
- S2: 19 plays, -7.75%.
- S0 ML: 6 plays, -4.37% (roughly near break-even compared with 2023 collapse).
- S2 ML: 4 plays, -39.5%.
- first AMBER: Week 6 after 3 observations.
- first RED: Week 14 after 9 observations.
- S2 shifted additional volume toward spreads and created 3 RED no-play blocks.

Thus the same protection that helped in 2023 was too cautious in a merely mediocre 2024 ML environment and reduced overall performance.

## What this establishes

1. A causal dynamic trust mechanism can limit a dying ML betting edge without knowing the regime break in advance.
2. Trust must be measured on the selector's top ML frontier, not the broad eligible pool.
3. A two-stage AMBER/RED response can preserve strong 2020–2022 behavior while responding materially earlier in 2023.
4. The mechanism is not sufficient for promotion because it can overreact in a mild down period such as 2024.
5. Most importantly, **ML de-prioritization hands the decision to spread Value**, and spread confidence/selection is still not trustworthy enough. In 2023 the S2 replacement spread stream was -23.57% ROI.

## Recommended next step

Do not tune AMBER/RED thresholds further on already-exposed 2023–2024.

The ML adaptive-trust concept should be retained as a candidate guardrail, but final Value policy should wait until the separate spread model-confidence problem is corrected/validated. Once spread confidence is trustworthy, rerun the already-preregistered state-machine concept without threshold fishing and assess whether ML-to-spread substitution becomes genuinely protective.

2025 remains sealed for future true validation.