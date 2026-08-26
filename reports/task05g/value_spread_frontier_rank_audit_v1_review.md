# Task05G Value Spread Frontier Rank Audit V1 Review

Verdict: `2023_VALUE_FAILURE_PRIMARILY_RANK1_ANTI_SELECTION_RAW_MARGIN_FRONTIER_REINTRODUCED_EXTREMITY_RISK`

This was a preregistered retrospective diagnostic only. No Task05F evaluator, football model, Spread Confidence V3 mapping, production selector, candidate family, state threshold, staking rule, or 2025 data was changed.

## Evidence identity

- preregistration commit: `5501ce6f2aefb6db48ad253d99f5ea93a4449712`
- workflow: `32922904018` — SUCCESS
- artifact: `9590452246`
- digest: `sha256:d29c9a2c0eea16ba4988020e058111e2ed41c90374ec272b6fae65bdce6a07b5`
- deterministic double replay: PASS
- frozen tests: PASS
- Task05F reproduction: PASS
- Model Confidence V2 reproduction: PASS
- Spread Confidence V3 reproduction: PASS
- 2025 firewall: PASS

## 1. Primary 2023 finding

The severe 2023 Value collapse was **not primarily a broad Expected-Margin spread-Value population collapse**.

Final strict spread-Value audit population, 2023:

- 22 exact-shopped candidates across 12 blocks
- 10 wins, 11 losses, 1 push
- 47.62% non-push hit rate
- **-8.68% flat 1u ROI**
- average odds -109.9
- average raw `model_cover_margin_v3` 2.51 points
- average Spread V3 q 50.996%
- average exact Task05F EV +2.22%
- average evaluator edge +1.20pp

The population was mildly losing, but nowhere close to the final weekly-frontier catastrophe.

### Current rank-1 spread frontier, 2023

- 12 plays
- **3 wins, 9 losses**
- **25.0% hit rate**
- **-51.81% ROI**
- average odds -108
- average raw cover margin 2.85 points
- average Spread V3 q 51.06%
- average exact EV +1.92%
- average evaluator edge +1.02pp

### Lower ranks, 2023

Rank 2:

- 5 candidates
- 3 wins, 1 loss, 1 push
- **75.0% non-push hit**
- **+33.43% ROI**
- average raw cover margin 2.46
- average Spread V3 q 50.98%

Rank 3:

- 3 candidates
- 2 wins, 1 loss
- **66.67% hit**
- **+27.83% ROI**
- average raw cover margin 2.10
- average Spread V3 q 50.94%

All non-rank-1 candidates combined:

- 10 candidates
- 7 wins, 2 losses, 1 push
- **77.78% non-push hit**
- **+43.08% ROI**

This is strong evidence of **conditional rank-1 anti-selection / optimizer's curse** in 2023.

It does **not** authorize selecting rank 2. Rank 2/3 outcomes are exposed retrospective evidence only.

## 2. Paired evidence

In blocks where rank 1 and rank 2 both existed (5 paired blocks):

- lower rank won while rank 1 lost: 2
- rank 1 won while lower rank lost: 1
- both won: 1
- both lost: 0
- push-involved: 1

Rank 1 exceeded rank 2 on average by:

- +1.58 raw cover-margin points
- only +0.29pp Spread V3 q
- +0.83pp exact EV
- +0.41pp evaluator edge

Thus the raw-margin jump used to select rank 1 corresponded to only a tiny calibrated probability increase.

In blocks where rank 1 and rank 3 both existed (3 paired blocks):

- lower rank won while rank 1 lost: 2
- rank 1 won while lower rank lost: 0
- both lost: 1

Rank 1 exceeded rank 3 by +2.36 raw cover-margin points but only +0.55pp Spread V3 q.

The decisive issue is not that rank 1 always had weaker Task05F economics. In paired blocks rank 1 often also had slightly higher estimated EV/evaluator edge. The failure is more consistent with **conditioning on the maximum of noisy correlated estimates**, especially raw Expected-Margin extremity.

## 3. Why this reconnects to Spread Confidence V3

Spread Confidence V3 was built specifically because raw Expected-Margin magnitude did not support the earlier extreme spread-confidence tail. V3 directly calibrates raw `model_cover_margin_v3` into a much narrower cover probability.

The final Value candidate then reintroduced raw magnitude as the *primary frontier rank*:

```text
spread frontier rank:
1. model_cover_margin_v3 descending
2. evaluator edge
3. reliability
4. odds
```

That means the selector again rewards the largest raw Expected-Margin number even when V3 says the calibrated probability difference is tiny.

2023 makes this visible:

- rank 1 average raw margin: 2.85
- rank 2 average raw margin: 2.46
- difference: ~0.39 points across all observations, larger in paired blocks
- rank 1 average V3 q: 51.06%
- rank 2 average V3 q: 50.98%
- difference: only ~0.08pp overall

The raw-margin ordering is therefore creating much more ranking separation than the validated confidence layer supports.

This is the clearest architectural root cause found in the audit.

## 4. Not a simple price/juice problem

2023 rank-1 spread candidates averaged -108.

Price buckets:

- -110 to -101: 10 rank-1 plays, 20% hit, -61.11% ROI
- -120 to -111: 2 rank-1 plays, 50% hit, -5.36% ROI

The catastrophe was concentrated in ordinary near-even spread prices, not heavy juice.

## 5. Not one frozen disagreement bucket

2023 rank-1 results by Task05E bucket:

- 0-1: 1 play, 0-1, -100%
- 1-2: 4 plays, 1-3, -50.49%
- 2-3: 2 plays, 1-1, -4.55%
- 3-4: 5 plays, 1-4, -62.14%

The 3-4 bucket was bad, but the failure was not confined to it. This argues against deleting one Task05E subregion as the primary fix.

## 6. Cross-season context

Rank 1 is **not universally bad**:

| Season | Rank-1 plays | Hit rate | ROI |
|---|---:|---:|---:|
| 2020 | 8 | 50.0% | -4.70% |
| 2021 | 16 | 68.75% | +31.64% |
| 2022 | 11 | 81.82% | +57.32% |
| **2023** | **12** | **25.0%** | **-51.81%** |
| 2024 | 13 | 76.92% | +44.74% |

Overall 2020-2024 rank 1 was 61.67% hit and +17.65% ROI.

Therefore the correct conclusion is **not** `RANK1_ALWAYS_BAD` or `USE_RANK2`.

The problem is that an always-max-raw-margin frontier is **fragile to a season/regime in which raw Expected-Margin extremity loses ordering value**. Because rank 1 is excellent in 2021, 2022, and 2024, simply replacing rank 1 with a lower fixed rank would destroy genuine signal.

## 7. Full population context

2020-2024 strict spread-Value population:

- 139 candidates across 60 blocks
- 80 wins, 57 losses, 2 pushes
- 58.39% non-push hit
- **+11.63% ROI**

Development 2020-2022 population:

- 94 candidates
- 56.99% hit
- +9.30% ROI

Exposed 2023-2024 population:

- 45 candidates
- 61.36% hit
- +16.51% ROI

So the frozen Expected-Margin 0-4 strict-Value family remains broadly viable. The product risk is the **weekly frontier-selection mechanism**, not the existence of spread Value itself.

## 8. Root-cause verdict

The evidence best supports:

1. **Primary: rank-1 optimizer / conditional anti-selection in 2023.**
2. **Primary architectural mechanism: ranking by raw `model_cover_margin_v3` reintroduced model extremity after V3 had already shown that raw magnitude should be heavily compressed into calibrated probability.**
3. Secondary: the 2023 full population was mildly negative, so the season was genuinely harder; however that does not explain the -51.8% rank-1 collapse.
4. Not primary: juice/price.
5. Not primary: one Task05E disagreement bucket.
6. Not supported: blindly selecting rank 2 or rank 3.

## 9. Recommended next test

Do **not** tune raw-margin thresholds or choose a lower fixed rank.

The next selector test should remove raw `model_cover_margin_v3` as an unrestricted primary maximization target while preserving football-model provenance.

The cleanest candidate is a **two-stage corroborated spread frontier**:

1. eligibility remains exactly the frozen Expected-Margin 0-4 strict-Value universe;
2. football-model evidence remains mandatory through frozen Expected-Margin provenance and Spread V3 support;
3. rank using a conservative agreement/corroboration score based on already-available validated signals rather than maximum raw margin;
4. no candidate-count/coverage gate is loosened;
5. compare against the current raw-margin frontier across 2020-2024;
6. no threshold/coefficient grid;
7. 2025 remains sealed.

A separate preregistration is required before choosing the exact replacement score.
