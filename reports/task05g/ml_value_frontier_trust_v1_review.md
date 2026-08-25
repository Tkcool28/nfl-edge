# Task05G ML Value Frontier Trust V1 Review

Verdict: `FRONTIER_ALIGNMENT_FIXES_2022_FALSE_ALARM_BUT_REACTS_TOO_SLOWLY_IN_2023`

This was a preregistered retrospective diagnostic. No evaluator/model/production-policy/data/2025 changes.

Evidence:
- preregistration commit `4004d0898473e453ccaf8505bbabe3acb0f50172`
- preregistration blob `ebfaa57ebdb38b0062f5cec50e85b5acbd89aa8e`
- implementation/workflow head `d627b593e4517c6b7424eb480063912cac6c676d`
- workflow `32813117711` — SUCCESS
- artifact `9550504661`
- digest `sha256:87bfcb4a762a98e1407c5a1d6a3a7f822a1bb43b15235466c658a723d4886b84`
- deterministic replay PASS
- 2025 sealed

## Development 2020–2022

- F0 baseline: 50 plays, +32.91% ROI; ML 40 at +41.86%.
- F1 frontier shrink: 50 plays, +33.19%; ML 37 at +43.30%.
- F2 frontier shrink + RED: identical to F1 in development; RED never materially activated.

### 2022 false-alarm test

- F0 ML: 16 plays, +36.35% ROI.
- F2 ML: 15 plays, +35.94% ROI.
- trust fell below 0.50 only in Week 11 with 8 prior frontier observations.
- trust **never fell below 0.25** in 2022.

Thus frontier alignment fixed the broad-pool V1 failure that had incorrectly killed profitable 2022 ML by Week 5.

## Exposed stress replay 2023–2024

- F0: 39 plays, -24.29% ROI; ML 18 at -58.12%.
- F1: 39 plays, -22.87%; ML 17 at -52.39%.
- F2: 37 plays, -19.59%; ML 10 at -41.47%.

F2 retained 94.9% of baseline plays, so coverage was not neutered.

### 2023

- F0: 19 plays, -54.31%; ML 12 at -85.0%.
- F2: 18 plays, -41.16%; ML 5 at -64.0%.
- frontier trust dropped below 0.50 in Week 4, but with only one prior frontier observation.
- RED (<0.25 with >=8 prior observations) did not activate until Week 12 with 9 observations.

Thus frontier trust correctly recognized deterioration but the hard RED gate was too delayed to protect the first half of 2023.

### 2024

- F0: +4.23% ROI.
- F2: +0.85% ROI.
- frontier trust fell below 0.50 in Week 6 with 3 observations and below 0.25 in Week 14 with 9 observations.

## Interpretation

Two properties are now demonstrated:

1. Broad-pool trust reacts quickly but is misaligned and falsely kills good selector-frontier performance (2022).
2. Frontier-only trust is aligned and preserves 2022, but a RED-only state reacts too slowly in a severe early-season collapse (2023).

The next retrospective diagnostic should keep the same frontier trust formula and RED rule, and add an **AMBER state** that activates earlier without fully disabling ML:

- after >=3 prior frontier observations, if trust <0.50, any valid spread Value candidate gets priority over ML;
- ML remains eligible in AMBER if no spread Value candidate exists;
- RED remains trust <0.25 after >=8 observations and bars ML entirely;
- all constants are preregistered before replay;
- coverage remains guarded;
- 2023–2024 remain exposed stress evidence only and 2025 stays sealed.