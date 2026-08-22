# Task05F Primary Selectors V1 — Validation Evidence

Status: **VALID EXECUTION / HIGH-HIT ENCOURAGING / BALANCED AND VALUE V1 NOT ACCEPTED**

This report freezes the first preregistered 2020-2024 weekly evaluation of the three product cards over the accepted common candidate table. V1 selector rules are not changed from these results. All new observations remain `OBSERVATIONAL_ONLY_NOT_TUNED`. Season 2025 remains sealed.

## Reproducibility

- Selector evidence commit: `40ba6b1776524d5404afdc67bffb7f655d2224a9`
- GitHub Actions run: `32554577425`
- Artifact ID: `9471121681`
- Artifact ZIP digest: `sha256:a660d74fec0603a66fc0a865bcdac4b76a45c6562a4aa9ecab98a2026f57b8da`
- Development seasons: 2020-2024
- Sealed season: 2025
- Chronological slates: 109
- Card slots evaluated: 327
- Two complete weekly selector simulations: PASS
- Deterministic equality: PASS
- Candidate-table immutability: PASS
- Candidate outcome firewall before selection: PASS
- HIGH/MEDIUM primary-card reliability eligibility: PASS
- Balanced strict-positive-Value requirement: PASS
- Value strict-positive-Value requirement: PASS
- Evaluator-only scope guard: PASS

## Primary-card results

| Card | Plays | Coverage | Wins | Losses | Pushes | Hit rate ex-push | Flat ROI |
|---|---:|---:|---:|---:|---:|---:|---:|
| High Hit Rate | 60 | 55.05% | 37 | 23 | 0 | **61.67%** | **+1.30%** |
| Balanced | 56 | 51.38% | 26 | 30 | 0 | 46.43% | **-14.29%** |
| Value | 56 | 51.38% | 25 | 31 | 0 | 44.64% | **-9.70%** |

High Hit Rate selected 41 `VALUE` rows and 19 `PLAYABLE` rows. Balanced and Value selected only strict `VALUE` rows, as preregistered.

All 172 non-null card selections were `MEDIUM` reliability. No LOW or UNSUPPORTED row entered a primary card.

No total was selected because the accepted Phase-F totals board is LOW reliability. Market mix:

- High Hit Rate: 30 ML / 30 spread.
- Balanced: 21 ML / 35 spread.
- Value: 19 ML / 37 spread.

Duplicate recommendations are allowed by product contract. Of 56 slates with at least two non-null cards, 36 had at least two cards choose the same wager: 64.29%.

## Per-season evidence

2020 produced no eligible primary-card plays because chronological support/reliability had not reached recommendation quality. Coverage ramped naturally thereafter.

High Hit Rate:
- 2021: 4 plays, 50.0% hit, -6.52% ROI.
- 2022: 14 plays, 71.43% hit, +35.13% ROI.
- 2023: 21 plays, 47.62% hit, -23.08% ROI.
- 2024: 21 plays, 71.43% hit, +4.63% ROI.

Balanced:
- 2021: 4 plays, 50.0% hit, -4.68% ROI.
- 2022: 12 plays, 58.33% hit, +11.67% ROI.
- 2023: 20 plays, 30.0% hit, -42.96% ROI.
- 2024: 20 plays, 55.0% hit, -3.11% ROI.

Value:
- 2021: 4 plays, 25.0% hit, -53.26% ROI.
- 2022: 12 plays, 66.67% hit, +28.33% ROI.
- 2023: 20 plays, 30.0% hit, -26.66% ROI.
- 2024: 20 plays, 50.0% hit, -6.84% ROI.

## Structural diagnosis

V1 confirms that the common candidate table and deterministic weekly selection machinery work, but it also exposes a known architectural omission in the first selector policy.

The accepted Task05F architecture intentionally separates two axes:

1. calibrated fair-value probability / exact-offer EV; and
2. raw frozen football-model signal / model-market disagreement.

V1 primary selectors ranked only the first axis. That is especially problematic for moneyline because ML V4 was accepted as the fair-value probability base while its full-board universal Value edge was explicitly **not proven**. The raw QB-Elo/XGB football opinion was intentionally kept separate for downstream use, but V1 did not require it to support the selected wager.

This is visible in V1 ML selections: many high-probability or high-EV ML candidates were selected even when the frozen football-model probability was below the calibrated market/fair probability for that same side.

### Additional market-split observation

The following is a post-evidence diagnostic and is therefore explicitly `OBSERVATIONAL_ONLY_NOT_TUNED`; it does not change V1 rules and is not a threshold search.

- High Hit Rate spread selections: n=30, 63.33% hit, **+19.86% ROI**.
- High Hit Rate ML selections: n=30, 60.0% hit, **-17.25% ROI**.
- Balanced spread selections: n=35, 60.0% hit, **+14.29% ROI**.
- Balanced ML selections: n=21, 23.81% hit, **-61.92% ROI**.
- Value spread selections: n=37, 56.76% hit, **+8.91% ROI**.
- Value ML selections: n=19, 21.05% hit, **-45.93% ROI**.

This does **not** justify a market-specific ROI cutoff or removing ML because it lost historically. It does reinforce the pre-existing architecture requirement that a primary recommendation should not be promoted solely from fair-value EV when the frozen football inference points the other way.

## V1 decision

- **HIGH_HIT_RATE_V1: ENCOURAGING_BUT_NOT_FINAL** — overall 61.67% hit and slightly positive ROI, but the 2023 instability and ML architecture omission prevent final promotion.
- **BALANCED_V1: NOT_ACCEPTED.**
- **VALUE_V1: NOT_ACCEPTED.**
- **SELECTOR_PACKAGE_V1: VALID_EXECUTION_NOT_PROMOTED.**

V1 remains frozen as evidence. Its rules will not be edited after these results.

## Pre-existing theory for a separate V2

Before this selector evidence, Task05F had already established that fair-value probability and raw football signal are separate downstream axes. The previously documented direction-only football-support definitions are:

- Moneyline: selected-side raw exact AVG probability is greater than the selected-side calibrated fair-value probability.
- Spread: frozen Expected Margin gives the selected side positive point cushion at the exact actionable spread.
- Total: frozen R4 gives the selected over/under positive point cushion at the exact actionable total.

A separately preregistered selector V2 may require that **direction-only support gate** before a wager is primary-card eligible. It may not introduce a magnitude threshold, ROI bucket, market-specific selector threshold, historical coverage target, or sealed-2025 information. V1 results may not be used to tune the size of any football-disagreement requirement.
