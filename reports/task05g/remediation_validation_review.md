# Task05G Remediation V1 — Validation Review

Verdict: `TASK05G_REMEDIATION_PARTIAL`

The preregistered architecture is mechanically valid and materially improves the Value lane, but the complete three-lane recommendation policy is **not promotable** because Balanced remains strongly negative and the combined unique headline stream loses money. No thresholds, regions, ranking rules, robust-EV formula, football models, or Task05F evaluator parameters were changed after observing these results.

## 1. Preregistration and validation identity

- Frozen preregistration commit: `4b860cd1c87d605d26b305a7d7c90c8a1f34f315`
- Frozen Task05F main baseline: `4984ea1ee38377f7f5016d2081be8f7c43bda4cd`
- Authoritative remediation implementation validated before this report-only commit: `875345b0679445cb75b132b9f1ec8251fe942ae7`
- CI-only validation branch added one throwaway text trigger after that implementation commit; no betting/evaluator/model code differed.
- Standalone remediation workflow run: `32709287930` — SUCCESS
- Existing Task05G workflow run with remediation gates: `32709287883` — SUCCESS
- Standalone evidence artifact: `9513491523`
- Standalone artifact digest: `sha256:a3b16d9c196347a5a0a56e510f6cc7920236762b54b71412f75810d0855e8964`
- Existing-workflow evidence artifact: `9513503672`
- Existing-workflow artifact digest: `sha256:fe0ee83fc60120266f6aeb9011f162950d35497cde3ce03c78b2443626b2521b`

Both workflows passed preregistration proof, frozen-scope proof, focused tests, regenerated Task05F board, 2025 firewall, deterministic replay, original-policy parity, remediation guardrails, security checks, and evidence upload.

## 2. What was tested

The frozen remediation architecture was:

`Task05E football-model candidate side -> Task05F exact DK/FD offer evaluation -> Task05G remediation selector`

Generic full-board evaluator `VALUE` could no longer create a headline candidate side.

Frozen candidate regions:

1. `ML_DOG_VALUE_ZONE / AVG / ZONE`
2. `ML_DOG_VALUE_ZONE / CORROB / ZONE`
3. `ML_AVG_DISAGREEMENT / AVG / 0-2`
4. `SPREAD_DISAGREEMENT / EXPECTED_MARGIN / 0-4 union`
5. No totals headline family

Historical Task05E price/line and outcome fields were not candidate identity. Candidate identity was game + market + selected side. Task05F evaluated the exact available DK/FD offer on that side.

Balanced ranking was preregistered probability-first. Value required positive one-uncertainty-radius robust EV and ranked robust EV instead of maximum point EV. Units, risk profiles, shopping, and Play Through mechanics were unchanged.

## 3. Original-policy parity

The remediation runner reran the preserved Task05G V1 policy on the same regenerated board and reproduced the known play counts exactly:

| Lane | Original plays | Original ROI |
|---|---:|---:|
| Hit Rate | 59 | +6.30% |
| Balanced | 67 | -15.12% |
| Value | 61 | -18.45% |

This proves the comparison was not created by changing the historical board or original policy universe.

## 4. Remediation headline results

| Lane | Plays | Hit rate* | ROI / unit | Market mix |
|---|---:|---:|---:|---|
| Hit Rate | 15 | 73.33% | **+20.47%** | 11 ML / 4 spread |
| Balanced | 49 | 41.67% | **-24.90%** | 11 ML / 38 spread |
| Value | 10 | 44.44% | **+6.23%** | 8 ML / 2 spread |

\*Non-push hit rate.

No remediation headline was a Total. No headline lacked frozen model-candidate provenance. Value had zero longshot-guardrail violations.

## 5. Hit Rate by season

| Season | Plays | ROI |
|---|---:|---:|
| 2020 | 0 | — |
| 2021 | 1 | +59.17% |
| 2022 | 5 | +31.01% |
| 2023 | 5 | -35.90% |
| 2024 | 4 | +68.09% |

Aggregate performance is positive but evidence is sparse: only 15 plays, one play in 2021, and no 2020 plays. It is not sufficient by itself for a strong promotion claim.

The selected Hit Rate population came from 11 ML AVG 0-2 memberships and four Expected Margin spread 0-4 memberships. The dog-value regions do not naturally enter Hit Rate because their model definition is a 40%-50% dog probability zone.

## 6. Balanced by season

| Season | Plays | ROI |
|---|---:|---:|
| 2020 | 0 | — |
| 2021 | 4 | -12.48% |
| 2022 | 13 | -5.53% |
| 2023 | 16 | **-82.07%** |
| 2024 | 16 | +13.42% |

Balanced remains a decisive failure.

Its 49 selections were 11 ML and 38 spread. In 2023, the breakdown was two ML at -100% ROI and 14 spreads at approximately -79.50% ROI. This is not cured by removing Totals or generic evaluator-created candidate sides.

The remediation did fix the prior direct ranking defect (VALUE no longer outranks probability), but that repair alone does not make Balanced economically valid.

## 7. Value by season

| Season | Plays | ROI |
|---|---:|---:|
| 2020 | 0 | — |
| 2021 | 3 | -18.33% |
| 2022 | 5 | +5.60% |
| 2023 | 2 | +44.64% |
| 2024 | 0 | — |

Value changed materially relative to V1:

- plays: 61 -> 10
- ROI: -18.45% -> **+6.23%**
- Totals: 12 -> 0
- average point EV: +9.76%
- average robust EV: +1.67%
- all selected Value offers were MEDIUM reliability

Candidate-region memberships among the ten selections (overlap allowed):

- ML dog-value AVG: 8
- ML corroborated dog-value: 5
- ML AVG 0-2: 1
- Spread Expected Margin 0-4: 2

This supports the forensic hypothesis that restoring model-derived candidate provenance and refusing max point-EV ranking fixes a major part of the Value pathology. It does **not** establish a production-ready Value policy because the sample is only ten plays, there are no 2024 plays, and 2021 remains negative.

## 8. Candidate survival through Task05F

The model-first registry produced 1,202 unique candidate sides represented on the Task05F board:

- 402 moneyline
- 800 spread
- 0 total

Task05F / exact-offer survival counts after shopping:

- model candidate sides: 1,202
- supported: 1,086
- HIGH/MEDIUM reliability: 711
- VALUE or PLAYABLE: 353
- strict VALUE: 273

Therefore the issue is not simply that the evaluator can find almost no exact offers. There is substantial candidate survival before final selector eligibility/ranking.

Region membership counts on the candidate board (overlap allowed for ML):

- ML AVG 0-2: 216
- ML dog-value AVG: 232
- ML corroborated dog-value: 140
- Spread Expected Margin 0-4: 800

## 9. Frozen Task05E candidate baselines over 2020-2024

These are reporting baselines only; outcomes were not used to build candidate eligibility.

### ML AVG 0-2

- overall: 216 plays, -3.71% ROI
- 2020 +13.80%
- 2021 +10.79%
- 2022 +15.85%
- 2023 -60.84%
- 2024 +0.48%

### ML dog-value AVG

- overall: 232 plays, +5.10%
- 2020 +43.22%
- 2021 +29.90%
- 2022 +10.76%
- 2023 -28.55%
- 2024 -15.72%

### ML corroborated dog-value

- overall: 140 plays, +4.53%
- 2020 +49.83%
- 2021 +23.87%
- 2022 +15.00%
- 2023 -25.59%
- 2024 -42.00%

### Spread Expected Margin 0-4

- overall: 800 plays, +5.54%
- 2020 +5.11%
- 2021 +4.39%
- 2022 +19.83%
- 2023 -8.74%
- 2024 +7.04%

This confirms two facts simultaneously:

1. The earlier architecture bug was real; generic evaluator selection had discarded model-edge provenance.
2. Some frozen model regions also genuinely weakened later, especially ML dog regions in 2023-2024 and ML AVG 0-2 in 2023.

The model evidence is therefore not a five-year uniformly stationary edge.

## 10. Combined headline stream and risk profiles

After deduplicating exact offers shared by multiple roles, the remediation produced 59 unique headline wagers:

- 25 wins
- 33 losses
- 1 push
- unweighted ROI per wager: approximately **-19.06%**
- ML union: 20 wagers, approximately +1.25% ROI
- spread union: 39 wagers, approximately -29.47% ROI

The combined stream is dominated by Balanced's losing spread selections.

All five unchanged bankroll profiles lost money:

| Profile | Ending bankroll | Max drawdown |
|---|---:|---:|
| Cautious | $975.34 | 4.90% |
| Steady | $957.72 | 7.57% |
| Balanced | $942.15 | 10.18% |
| Bold | $927.80 | 12.59% |
| High Gear | $911.94 | 15.15% |

Starting bankroll was $1,000. The staking policy is not diagnosed as the cause; profiles magnify the same losing combined selection stream.

## 11. What the remediation proves

The preregistered test supports the central forensic diagnosis for **Value**:

- model provenance matters materially;
- generic full-board evaluator VALUE was not an adequate candidate-discovery mechanism;
- removing unsupported Totals candidate discovery matters;
- max point-estimated EV was a poor universal ranking statistic;
- model-first + exact-price evaluation can recover a much smaller positive-ROI Value subset in development evidence.

It also proves the original Balanced problem was **not only** its VALUE-first lexicographic bug. Even after probability-first ordering and model-candidate gating, Balanced remains strongly negative.

## 12. Why Balanced still deserves upstream diagnosis

Balanced's primary ranking statistic is still Task05F actionable probability. For ML and especially spread in later historical blocks, the forensic audit already showed Task05F frequently gives the football model zero incremental weight after market calibration.

Thus candidate provenance is now preserved as an eligibility gate, but Balanced can still rank the surviving model candidates chiefly by a market-derived probability rather than by the strength/quality of the football-model disagreement that created the candidate.

This is a structural hypothesis for the next diagnostic, not a post-hoc replacement rule. No alternative model-edge ranking was tested or adopted in this remediation run.

## 13. 2020 coverage caveat

All three recommendation lanes produced zero 2020 headlines, just as the original Task05G chronology did. The expanding Task05F support/calibration state had not matured enough to produce eligible headline offers early in the chronology.

Therefore this remediation does not demonstrate that the evaluator preserves the strong 2020 model-region ROI in actionable recommendation form.

## 14. Final verdict

`TASK05G_REMEDIATION_PARTIAL`

- Architecture/mechanics: PASS
- Preregistration integrity: PASS
- Frozen scope / 2025 firewall: PASS
- Original-policy parity: PASS
- Hit Rate evidence: POSITIVE BUT SPARSE
- Value evidence: MATERIAL IMPROVEMENT, POSITIVE BUT TOO SPARSE/UNSTABLE FOR PROMOTION
- Balanced evidence: FAIL
- Combined headline portfolio: FAIL
- Production promotion: NO

## 15. Recommended next step

Do **not** tune this remediation against the observed outcomes.

Next, perform a read-only stage-by-stage evaluator/model-provenance audit inside the frozen Task05E candidate population, especially for Balanced/spread:

1. raw frozen model candidate;
2. Task05F supported;
3. HIGH/MEDIUM reliability;
4. VALUE/PLAYABLE;
5. selector probability ordering;
6. exact realized ROI by season/market at each stage;
7. trace model disagreement magnitude/direction versus Task05F actionable probability ordering.

The purpose is to locate exactly where profitable model-region populations become anti-selected, without proposing another ranking rule from these same outcomes. If that audit shows the evaluator/ranking systematically suppresses or reverses model-edge ordering, the next architecture should preserve model-edge strength as a distinct ranking axis before any new historical policy is tested.
