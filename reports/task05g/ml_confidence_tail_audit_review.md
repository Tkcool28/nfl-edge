# Task05G ML Confidence High-Tail Audit Review

Verdict: `ML_CONFIDENCE_NOT_SPREAD_STYLE_BROKEN_HEADLINE_MAX_SELECTION_ANTI_SELECTION_LOCALIZED`

This is a read-only diagnostic stacked on the validated Spread Confidence V3 experiment. It does **not** change the football models, Task05F evaluator, ML confidence calibration, Spread Confidence V3, HHR/Balanced selectors, thresholds, units, historical data, or production policy. 2025 remains sealed.

## Evidence identity

- frozen audit plan branch: `audit/task05g-ml-confidence-tail-v1`
- validated audit code commit: `084ea8ada35b0a5adf321711bc7cccc05674546c`
- workflow run: `32836785347` — SUCCESS
- artifact: `9558956836`
- artifact digest: `sha256:9dcacb02416e610d3bd92a15bb25fb69fde7b9b5dda4ae66fe2c2eb668b18830`
- deterministic double replay: PASS
- audit-only scope: PASS
- focused tests: PASS
- 2025 firewall: PASS

## 1. ML does not reproduce the Spread V2 confidence pathology

The broad ML probability scale is not showing the same structural failure that turned 8–12 point spread disagreements into 75–85% cover confidence.

Exact-shopped supported ML calibration in 2020–2022:

- 65–70% bucket: mean q 67.40%, realized 75.23%
- 70–75%: mean q 72.32%, realized 81.94%
- >=75%: mean q 80.66%, realized 75.00%

Exact-shopped supported ML calibration in locked 2023–2024 diagnostics:

- 65–70%: mean q 67.30%, realized 66.23%
- 70–75%: mean q 72.08%, realized 63.27%
- >=75%: mean q 80.60%, realized 80.82%

The upper tail is not perfectly monotonic in every exposed period, but there is no spread-style 20–35pp systematic inflation across the high-confidence population. The >=75% population is only modestly overconfident in development and essentially exact in 2023–2024.

The prior V2 aggregate calibration slopes were also near one in both periods, consistent with this result.

## 2. The failure appears after selecting the maximum-confidence headline

The strongest development finding is rank inversion inside the actual selector-eligible ML pool.

### HHR, 2020–2022

Rank 1 by the frozen HHR ML ordering:

- n = 42 non-push headlines
- average model confidence 70.81%
- realized hit rate 54.76%
- calibration error -16.05pp
- average raw QB-Elo/XGB probability 67.28%
- calibration lift +3.53pp
- average QB-Elo/XGB absolute disagreement 13.26pp
- average break-even 66.32%
- average odds -199
- ROI -18.62%

Rank 2:

- n = 41
- average model confidence 66.50%
- realized hit rate 75.61%
- calibration error +9.11pp
- average raw probability 62.88%
- calibration lift +3.62pp
- QB-Elo/XGB disagreement 8.97pp
- average break-even 63.57%
- average odds -172
- ROI +19.76%

Rank 3:

- n = 40
- average model confidence 64.14%
- realized hit rate 57.50%
- ROI -9.71%

The selector's highest stated ML probability was materially worse than the second-highest candidate despite carrying substantially greater claimed confidence and heavier average juice.

### Balanced B0, 2020–2022

Rank 1:

- n = 40
- average model confidence 68.22%
- realized hit rate 47.50%
- calibration error -20.72pp
- average raw probability 64.02%
- calibration lift +4.20pp
- QB-Elo/XGB disagreement 11.86pp
- average break-even 58.25%
- average odds -106
- ROI -17.67%

Rank 2:

- n = 36
- average model confidence 64.46%
- realized hit rate 63.89%
- calibration error -0.57pp
- average odds -94
- ROI +13.21%

Rank 3:

- n = 30
- average model confidence 61.94%
- realized hit rate 60.00%
- average odds -45
- ROI +15.41%

Again, max-confidence rank 1 was the anti-selected group.

This is consistent with a **conditional max-selection / winner's-curse problem**: the ML calibrator can be reasonably truthful over the full population while the extreme candidate chosen after maximizing stated confidence is not calibrated like a random row from the same probability bucket.

Because the chronological Platt transform is monotonic when supported, it does not create a different rank ordering from the underlying QB-Elo/XGBoost average within a block. The issue therefore cannot be repaired merely by rescaling the same probabilities while keeping `highest q wins` as the decision rule.

## 3. Raising the confidence floor does not solve development

The preregistered descriptive confidence-floor frontier directly tests the pick-frequency concern. It does **not** authorize selecting a new threshold from exposed results.

### HHR ML-only, 2020–2022

- >=55%: 43/65 play blocks (66.2% coverage), 54.8% hit, -18.6% ROI
- >=60%: 42/65 (64.6%), 56.1%, -16.6%
- >=65%: 34/65 (52.3%), 57.6%, -16.1%
- >=70%: 20/65 (30.8%), 47.4%, -31.3%
- >=75%: 14/65 (21.5%), 35.7%, -49.2%

### Balanced B0 ML-only, 2020–2022

- >=52%: 40/65 play blocks (61.5%), 47.5% hit, -17.7% ROI
- >=60%: 36/65 (55.4%), 47.2%, -22.1%
- >=65%: 27/65 (41.5%), 48.1%, -22.8%
- >=70%: 15/65 (23.1%), 46.7%, -25.6%
- >=75%: 8/65 (12.3%), 37.5%, -40.9%

Thus the development evidence does **not** say "accept fewer plays and accuracy rises." Above 70%, coverage collapses while accuracy also falls.

## 4. Locked 2023–2024 diagnostics are healthier but still non-monotonic

HHR rank 1 in 2023–2024:

- n = 35
- q 72.33%
- realized hit 68.57%
- ROI +5.34%

HHR descriptive floors:

- >=55%: 79.5% block coverage, 68.6% hit, +5.3% ROI
- >=65%: 68.2% coverage, 73.3% hit, +8.8%
- >=70%: 47.7% coverage, 76.2% hit, +10.4%
- >=75%: 31.8% coverage, 64.3% hit, -7.3%

Balanced rank 1:

- n = 35
- q 68.45%
- realized hit 60.00%
- ROI +5.23%

Balanced floors remain non-monotonic and do not establish a safe new cutoff.

Because 2023–2024 outcomes were already exposed during prior Task05G work, the apparently attractive HHR >=70% diagnostic must **not** be adopted as a production threshold from this audit.

## 5. Constituent-model disagreement is a plausible trust signal, not yet a rule

The development HHR rank-1 group had much larger average QB-Elo/XGBoost disagreement than rank 2:

- rank 1: 13.26pp
- rank 2: 8.97pp

The later 2023–2024 HHR rank-1 group was healthier and had only 8.06pp average disagreement.

Balanced shows a weaker version of the same pattern.

This makes model agreement/disagreement a plausible explanation for why the maximum ensemble probability can become less trustworthy. It is **not** enough evidence to retroactively impose an agreement threshold, because the relevant outcomes are now exposed.

## 6. Product implication

The current evidence does not support solving HHR/Balanced by simply raising the ML probability minimum. That would often produce **fewer picks without producing better picks**.

The next experiment should preserve the current ML calibrator and test a preregistered **headline trust / max-selection correction** rather than another global probability recalibration. Candidate mechanisms should be frozen before results, with explicit coverage diagnostics, and may examine:

- QB-Elo/XGBoost agreement as uncertainty/trust information;
- shrinkage of extreme headline confidence conditional on constituent disagreement;
- rank-1 versus near-rank candidate behavior without using realized ROI to choose a rule;
- whether a candidate should fail closed when the two football models disagree too strongly;
- product coverage so HHR/Balanced are allowed to return no distinct play rather than manufacturing three cards.

No threshold or disagreement cutoff is selected here. No production promotion is authorized. 2025 remains sealed.
