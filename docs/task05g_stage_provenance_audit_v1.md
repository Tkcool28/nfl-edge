# Task05G Stage-by-Stage Model/Evaluator/Selector Provenance Audit V1

This branch is diagnostic only. It does not change Task05F evaluators, football models, Task05G selector policy, Task05G remediation policy, Task05E candidate regions, or sealed 2025 data.

## Purpose

Trace where model and evaluator populations improve or degrade through the downstream recommendation pipeline, while keeping two universes distinct:

1. the intended full common evaluated-wager table used by HHR/Balanced/Value; and
2. the frozen Task05E model-region gate used only by the preregistered remediation experiment.

The frozen Task05E regions are **not** permanent HHR/Balanced eligibility.

## Stage audit

The stage audit reports:

- exact-shopped offers;
- Task05F supported;
- HIGH/MEDIUM reliability;
- VALUE or PLAYABLE;
- strict VALUE;
- HHR eligibility;
- Balanced eligibility;
- original full-board HHR/Balanced selections;
- remediation region-only HHR/Balanced selections;
- inside/outside frozen-region membership;
- Expected Margin spread ranking by evaluator probability versus raw disagreement;
- evaluator zero-versus-positive football-model influence.

## PLAYABLE / ML suppression follow-up

The follow-up audit separately measures:

- full HIGH/MEDIUM PLAYABLE outcomes by market, season, concession size, probability, odds, and evaluator negative-EV band;
- HHR and Balanced PLAYABLE coverage gained beyond strict VALUE;
- realized outcomes of the exact blocks created only by PLAYABLE;
- selected strict-VALUE versus selected PLAYABLE headline outcomes;
- ML frozen candidate transformations from raw QB-Elo/XGB AVG probability through raw Pinnacle, calibrated market probability, and final ML V4 probability;
- ML model-weight zero versus positive blocks;
- status decomposition inside frozen ML dog regions.

The corrected ML trace compares the raw football probability to Task05F's **calibrated market anchor** (`staking_anchor_probability` for ML), not raw Pinnacle probability.

## Guardrails

- 2025 hard sealed.
- No selector threshold changes.
- No Play Through corridor changes.
- No evaluator or model retuning.
- No candidate-region changes.
- No outcome-selected replacement rule.
- Deterministic double replay in CI.

Permanent evidence reviews:

- `reports/task05g/stage_provenance_audit_review.md`
- `reports/task05g/playable_ml_suppression_audit_review.md`
