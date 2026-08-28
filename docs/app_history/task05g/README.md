# NFL EDGE — Task05G App History

## Purpose

This directory preserves **application/model-development history**, not historical sports data.

`app_history` is intentionally separate from any repository paths that use `history` or `historical` for data ingestion, snapshots, seasons, or source pulls.

Task05G is complete. The canonical production contract is the implementation on `main`, especially:

- `docs/NFL_EDGE_TASK05G_MASTER_HANDOFF.md`
- `config/task05g_final_product_freeze_v1.yaml`
- `src/nfl_edge/recommendation/final_selectors_v1.py`
- `src/nfl_edge/recommendation/headline_staking_v1.py`
- `src/nfl_edge/recommendation/staking_v1.py`
- `src/nfl_edge/recommendation/product_policy_v1.py`

The PRs indexed below are **retired research/development branches**. They are preserved by Git/GitHub for provenance and reproducibility, but they are not alternate production implementations and must not be treated as supported policy paths.

No obsolete executable implementation is copied into this archive. Exact historical code remains recoverable from the recorded PR and head SHA.

## Retirement status

The following Task05G PRs were intentionally left unmerged during development because they were audits, failed/partial experiments, intermediate architecture checkpoints, or evidence that was later absorbed into the final production chain.

| PR | Head SHA | Disposition | What it established / why it is retired |
|---:|---|---|---|
| #25 | `f389223b3a77cc628e07750b620e6e77cf031763` | SUPERSEDED_PROTOTYPE | Original selector/staking implementation exposed Balanced mis-ranking, max-EV Value anti-selection, and loss of football-model provenance. Useful forensic baseline; not final policy. |
| #29 | `1e221c7dc44cc18328468cc47ff3b7201fa69b83` | PARTIAL_REMEDIATION | Restored model-first candidate provenance and improved Value, but Balanced/combined portfolio still failed. Led to deeper stage-by-stage audit. |
| #32 | `df617fe0f62feb86064487a961dbaa9e890af898` | AUDIT_ONLY | Localized evaluator/model-provenance problems and motivated a separate market-independent model-confidence layer. |
| #33 | `a1cc4256cc355a312c8831fc6134dc404dd0b3f4` | FAILED_EXPERIMENT | Model Confidence + Selector V2 passed development but failed 2023-24 confirmation, especially on spread confidence. Not promotable. |
| #35 | `11ea128736278f1b5860194aed9f7db3a77b6112` | AUDIT_ONLY | Diagnosed structural spread-confidence high-tail miscalibration rather than a simple 2023 variance shock. |
| #36 | `cc462736fba0538e3a674a2bc74658f9307df65a` | INCORPORATED_IN_FINAL_V1 | Spread Confidence V3 corrected the probability-conversion defect. Historical experiment branch retired after its validated behavior became upstream support for final Task05G. |
| #37 | `10e8b49b8443ea1726bc104bdc5565b925feb1ad` | AUDIT_ONLY | Showed ML confidence was broadly calibrated but headline max-selection created anti-selection / winner's-curse behavior. |
| #38 | `01b1e7d6958fc2e8de12c9fcd130b5789f88f58a` | MIXED_EXPERIMENT | Fixed QB-Elo/XGBoost disagreement penalty helped Balanced development but did not generalize cleanly and hurt HHR. Not promoted. |
| #39 | `7f7981e646f437ac633ec25255570e1b8a82b7c5` | AUDIT_ONLY | Ruled out retail overjuice as the primary HHR failure and identified sharp-market corroboration as the more relevant signal. |
| #40 | `df8b6e1f75ae0eda4627d5228562f29df60636ff` | INCORPORATED_IN_FINAL_V1 | Preregistered `HALF_SHRINK` market corroboration. Formal gate narrowly missed, but later bounded architecture evidence supported the same frozen transform used in final HHR. |
| #41 | `9d73539188ea36dadaf4feab6df6ba6b480fc4b1` | ARCHITECTURE_CHECKPOINT | Re-established HHR, Balanced, and Value as three separate protocols. Final implementation supersedes this checkpoint. |
| #42 | `b93b21a11091411a4c35def40ca704a2aaf858d3` | SUPERSEDED_CANDIDATE | Tested the final-candidate architecture before later Value safety work. HHR direction survived; Balanced/Value needed further refinement. |
| #43 | `3d5e030b802646abef0aa3bb23ccd5a83510277a` | AUDIT_ONLY | Localized 2023 Value spread failure to raw-margin rank-1 anti-selection rather than the whole Expected-Margin candidate population. |
| #44 | `06ba4c1a7c1dca215e691d2a6a23758dfae6ad35` | FAILED_EXPERIMENT | Dual family trust detected spread deterioration but shifted too much volume into unhealthy ML and did not solve 2023 Value. |
| #45 | `bf5313730c4fb8d118e63ae21b001e4952421d9a` | PARTIAL_IMPROVEMENT | Pareto spread ranking preserved spread opportunity and improved stability but did not contain the full 2023 Value failure. |
| #46 | `046a57f2be1cf53f86012fae03b57fb92fc08714` | FAILED_EXPERIMENT | Regime/depth interaction was real, but blanket RED spread suppression was too blunt and removed good competitive spreads. |
| #47 | `d9cce094596374960633b336319e4278cd95669f` | INCORPORATED_IN_FINAL_V1 | Non-GREEN singleton spread fail-safe selectively reduced abnormal spread damage while preserving competitive spreads. Absorbed into final Value safety semantics. |
| #48 | `3cc07b552ae59d0c0aaffb1b4445c96eeeb30305` | AUDIT_ONLY | Localized residual later-period ML Value failures to non-mature singleton ML with no valid spread frontier. |
| #49 | `131a45ce1e790309ec26bf9cc081f11ce3d668f6` | INCORPORATED_IN_FINAL_V1 | Bounded COLD/AMBER singleton ML fail-safe produced the accepted final Value safety behavior later frozen in the production selector chain. |
| #53 | `33a3428e228d0e8073b2bb9ea7340a851a13fb1f` | AUDIT_ONLY | HHR staking audit established positive post-selection staking, price-pressure haircut behavior, 0.25u floor, and heavy-juice warning concept. |
| #54 | `4e43ac7bcf55412d7097dc1424aa124c2b2968e5` | AUDIT_ONLY | Final 2020-24 product replay audit tested follow-every-current-headline staking and bankroll behavior without changing selectors. |
| #55 | `d39bb1e9f4c41d911c85a3b93ae09084ada23f03` | INCORPORATED_IN_FINAL_V1 | Final actionability audit established Balanced 0.75u floor and bounded Value-at rescue behavior later integrated canonically by PR #56. |

## Canonical production chain

The retired branches above culminated in the reviewed stacked development chain:

`#50 -> #51 -> #52 -> #56`

Because those PRs were intentionally stacked on feature-branch bases, they did not themselves place Task05G on `main`. Their reviewed final state was promoted cleanly to `main` by **PR #59**, which is the canonical production merge for Task05G.

Current `main` is the production reference. The retired PRs in this index are research provenance only.

## Historical-code recovery

If an old experiment must be reproduced:

1. use the PR number and exact head SHA above;
2. inspect or check out that historical commit explicitly;
3. keep reproduction isolated from production code paths;
4. do not copy an old selector/staking implementation back into canonical modules without a new reviewed design decision.

Closed PRs preserve their discussion, diffs, commits, workflow references, and exact historical branch ancestry even after their remote branch is eventually deleted.

## 2025 boundary

All Task05G research indexed here treated 2025 as sealed. The final Task05G production freeze was completed on 2020-2024 evidence without opening or running 2025 for Task05G acceptance.

## Excluded from this cleanup

PRs **#19 and #20** are Task05F evaluator-development branches, not merely Task05G research branches. They require a separate comparison against the current canonical evaluator before any retirement decision and are intentionally excluded from this archive/cleanup pass.
