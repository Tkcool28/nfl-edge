# Task05F Locked Evaluator V1 — Consolidation Proof

Status: **LOCKED COMPONENT REPRODUCTION PASS / PLAY THROUGH NOT YET APPLIED**

This report preserves the deterministic consolidation of the accepted Task05F probability architectures into one common evaluator board. It introduces no new probability family and does not alter any football model.

## Frozen component architecture

- Moneyline: `ml_v4`
- Spread: `spread_v3`
- Total: `total_v3`
- Development seasons: 2020–2024
- Sealed: 2025
- Strict Value definition: `expected_value > 0`

## GitHub Actions evidence

- Feature commit validated: `a9a87b2f8af8a4c32aa769233e4e315d71eabebd`
- Pull-request merge ref executed: `61f2ab36e70cd38393c6500e1aae2dacb15f9eeb`
- Workflow run: `32548367894`
- Artifact ID: `9469335504`
- Artifact ZIP digest: `sha256:622de77985fa77edabf67f62b2c291591d1948ecb8df6af320f34e1c402a32fa`
- Locked config SHA-256: `cc0566a56c0a6a0bee78b9f572b0dc70d1d3be8fbd16b7c6377f1e734b337fb5`
- Evaluator-only scope guard: PASS
- Value-layer tests: PASS
- 2025 firewall: PASS
- Two complete locked chronological runs: PASS
- Deterministic output comparison: PASS

## Exact component reproduction

The consolidation runner executes the frozen component runners and fails closed unless the selected rows reproduce their source components logically.

- Locked total rows: **8,448**
- Moneyline rows: **2,816**
- Spread + total rows: **5,632**
- `moneyline_rows_equal_v4`: **true**
- `spread_total_rows_equal_v3`: **true**

Component artifact hashes from the proof run:

- V4 ML full board: `1b787a6117b4abc6870e809f0fe697a88e5f91f74c1aae3c55852e2633527926`
- V4 ML scorecard: `b1267386027f3dfcc7614f5fd46ddcd347aa7b4d0a90d0d37436735f3aaa2017`
- V3 full board: `54f95cfd8af374ebb09f4701e4593a04e2efa3b8ce6f5422ed64c95dc1f70192`
- V3 scorecard: `484bd8cff5125608abcc6dbbb62e6f5dda2b0c326a203bcd7255655886c26886`

## Locked-board diagnostics

These are descriptive evidence only; no new tuning is performed here.

| Market | Supported | Strict +EV | Nonpositive EV | +EV realized ROI | Nonpositive realized ROI |
|---|---:|---:|---:|---:|---:|
| Moneyline | 2,202 | 754 | 1,448 | -4.76% | -4.71% |
| Spread | 2,548 | 385 | 2,163 | -1.54% | -4.16% |
| Total | 2,542 | 544 | 1,998 | -1.04% | -4.45% |

These full-board figures do not replace the frozen external Task05E preservation evidence. In particular, Spread V3 remains accepted because its probability quality is coherent and it materially enriched the previously frozen spread edge; ML V4 remains the accepted fair-value baseline without a demonstrated universal full-board ML Value edge; totals remains probability-usable but Value-weak.

## Next phase

The common locked board currently still has candidate `uncertainty=None` and `staking_probability=None` on the accepted V3/V4 rows. The next phase therefore does **not** change evaluator probability. It finalizes candidate-specific reliability/uncertainty and conservative staking probability using strictly prior out-of-sample locked-board evidence.

Only after that layer is frozen should the separate Play Through policy be defined and then the High Hit Rate / Balanced / Value selectors and Sleeper Watch consume the common candidate table.

2025 remains sealed throughout those steps.
