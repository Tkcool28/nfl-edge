# NFL EDGE — 2025 All-Model Input Certification V1

Verdict: **ALL_2025_MODEL_INPUTS_FROZEN_AND_CERTIFIED**

This report certifies input/materialization structure only. It contains no 2025 model accuracy, win/loss, ROI, profit, selector-performance, team-result, or weekly-result analysis.

## Core freeze

- 2025 promoted PBP: `data/frozen/task05c_pbp_2025_v1/play_by_play_2025.parquet` — SHA-256 `c6ecedd6d678cc37ed316b23ef84ee1ec6abb69c514bb11868a7ebd5a367df29` — 285/285 canonical games.
- 2025 GameObservation ledger: `data/derived/task05c_game_observations_2025_v1/game_observations_2025_v1.jsonl` — SHA-256 `5a78b506a1d2dc14f4948cd316346d09d863e603c61144716a242252df8f84e3` — 285/285 games.
- Before Week 1 prediction, eligible 2025 PBP/GameObservation state updates: **0**.
- Before every block, current-block visible observations: **0**; future-block visible observations: **0**.
- After reveal, exactly the complete current block becomes eligible for one atomic `TotalsBlockState.commit_block(...)`.

## Certification matrix

| Component | 2025 coverage | Schema | Chronology | Frozen compatibility | Missing dependencies |
|---|---:|---|---|---|---|
| Oracle QB-Elo | 285/285 games; 570/570 sides | PASS | PASS_PR70_BLOCK_PHYSICAL_SOURCE_EXCLUSION | PASS | none |
| conservative chronology-corrected XGBoost | 285/285 games; 570/570 candidate-rank-1 QB sides | PASS_EXACT_TASK03C_GAME_PLUS_QB_ASSEMBLY | PASS_QB_CUTOFF_TARGET_MASKING_AND_BLOCK_REVEAL_COMPATIBLE | PASS | none |
| Expected Margin V1 stable | 285/285 | PASS | PASS_PRE_RESULT_MASKABLE_POST_REVEAL_COMPLETE | PASS | none |
| Ridge Totals R4 alpha100 | 285/285 2025 observations plus accepted 2018-2024 bootstrap inventory | PASS_EXACT_90 | PASS_ATOMIC_COMPLETE_BLOCK_REVEAL | PASS | none |
| ML V4 evaluator | 285/285 canonical games | PASS | PASS_FROZEN_T60_OUTCOME_BLIND | PASS | none |
| Spread V3 evaluator | 285/285 canonical games | PASS | PASS_FROZEN_T60_OUTCOME_BLIND | PASS | none |
| Total V3 evaluator | 285/285 canonical games | PASS | PASS_FROZEN_T60_OUTCOME_BLIND | PASS | none |
| schedule/context | 285/285 | PASS_AUTHORITATIVE_SOURCE_SPLIT | PASS_SCHEDULE_KICKOFF_PLUS_POINT_IN_TIME_CUTOFF | PASS | none |
| outcome/reveal/grading | 285/285 | PASS | PASS | PASS | none |
| downstream selectors/staking inputs | contract/source coverage | PASS_FROZEN_POLICY_SOURCES_PRESENT | PRE_RESULT_EVALUATOR_OUTPUTS_ONLY | PASS | none |

## Historical protection and determinism

- Protected tracked 2018–2024 artifacts byte-identical to starting main `d38c6544cdda687e14e58e3986f81e47a91a781d`: **PASS**.
- Accepted historical promoted-PBP inventory remains unchanged and retains its original 2018–2024 hashes; the current upstream 2024 asset is not substituted.
- New 2025 PBP is frozen byte-for-byte from the pinned nflverse release asset; derived GameObservation serialization is canonical and deterministic.
- The workflow independently builds the materialization twice and requires byte-identical generated outputs before staging.

## Final state

`remaining_missing_2025_input_surfaces: []`

**2025 HOLDOUT HAS NOT BEEN EXECUTED**
