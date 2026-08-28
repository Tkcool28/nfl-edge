# NFL EDGE — Pre-2025 Product Freeze V1

## Verdict

`PRE2025_PRODUCT_FREEZE_PARTIAL`

The promoted Task05F/Task05G product surface remains the intended production methodology and 2025 remains sealed. The repo is not yet ready for Master authorization to spend 2025 because the complete holdout-only execution adapter is not frozen.

## Starting Git state

- repository: `Tkcool28/nfl-edge`
- working branch: `chore/pre2025-product-freeze-v1`
- reference current main at task start: `65504d9d834d15d71d6fdc205a912eec455b66ab`
- Task05G clean promotion head: `4150fc411eb7450a8aeb8a13b076c278ddf3d28d`
- Task05G merge commit: `a684b046980c43e200ca87ce8d9165f9890c6696`

Commits after Task05G promotion were documentation/archive changes; no approved production selector/evaluator/staking semantics were reopened.

## Existing production freeze preserved

The existing `config/task05g_final_product_freeze_v1.yaml` remains authoritative for its production-methodology scope. This pre-2025 layer does not supersede its selector, staking, actionability, Play Through, default/manual, or legacy-quarantine semantics.

The new freeze extends identity coverage to the executable historical chain:

`Task05F evaluator -> Model Confidence V2 -> Spread Confidence V3 -> final selectors -> headline actionability -> units/risk profiles -> canonical product replay`.

## Historical identity / determinism proof

The accepted historical replay contract remains:

- evaluator seasons exactly 2020–2024
- 2025 absent
- HHR identity 81
- Balanced identity 88
- Value identity 68
- HHR current BET 81
- Balanced current BET 88
- Value current BET 40
- Value target-only 28
- published zero-actionable-unit headline 0
- 174 unique deduped current wagers
- 112-61-1
- 144.00u risked
- +8.05u weighted result
- Normal $1,000 bankroll ending $1,075.59
- +7.56% return
- 8.69% max drawdown

These remain exposed development diagnostics, not forward promises.

The prefreeze CI must rebuild the 2020–24 chain and run the final product replay twice, comparing the deterministic artifacts byte-for-byte.

## 2025 firewall proof approach

Preparation may inspect Git metadata for mixed 2018–2025 files, including tracked path, Git blob SHA, and size. It may not open their data contents to inspect, summarize, score, replay, or infer 2025 performance.

The prefreeze audit verifies sealed-path identity with `git ls-files -s`, which reads Git index metadata rather than parquet bytes.

The canonical one-shot gate:

- performs a code/config preflight
- requires an exact Master authorization phrase
- must verify authorization before any 2025 data read
- remains hard-blocked while `execution.ready: false`
- has no tuning flags
- is designed to support a one-spend marker once the executor is implemented

## Repository blocker 1 — 2025 football-model materialization

The accepted football-model runners are intentionally development-only:

- QB-Elo development walk-forward stops at 2024
- chronology-corrected XGBoost rejects 2025 at engine construction
- Expected Margin development path rejects the sealed holdout
- Ridge Totals R4 development preparation rejects 2025

That is correct development safety behavior. It must not be weakened globally.

Before authorization, a separate holdout-only adapter must be implemented and frozen that reuses the accepted model mathematics/hyperparameters while allowing only the authorized 2025 chronological path.

## Repository blocker 2 — 2025 historical market snapshots

Tracked canonical sportsbook inputs currently cover 2020–2024. The existing historical acquisition plan is likewise hard-frozen to 2020–2024.

The future holdout requires T-60 historical snapshots for at least:

- DraftKings
- FanDuel
- Pinnacle
- moneyline
- spread
- total

under the existing natural-kickoff-cluster policy.

A separately authorized 2025 plan/acquisition path must be frozen before the holdout is run. If equivalent 2025 artifacts exist outside the repo, they still require provenance/hash verification and explicit incorporation into the holdout contract before authorization.

## Canonical command surface

Preflight only:

```bash
python scripts/task05g_2025_holdout_one_shot_v1.py --preflight
```

Future one-shot command, intentionally blocked in this freeze:

```bash
python scripts/task05g_2025_holdout_one_shot_v1.py \
  --authorization MASTER_APPROVED_OPEN_2025_ONCE
```

No tuning, selector, threshold, profile, corridor, model-family, or market-family flags are permitted.

## Required pre-authorization correction

Implement and freeze the missing holdout-only upstream executor. It must:

1. validate the prefreeze manifest and protected identities
2. validate authorization before first 2025 read
3. materialize 2025 football predictions chronologically from frozen models
4. acquire/load and normalize authorized 2025 T-60 market snapshots
5. run the frozen Task05F evaluator family/state logic causally
6. run the frozen confidence/trust layers causally
7. run HHR/Balanced/Value without retuning
8. apply headline actionability, units, all five profiles, duplicate/slate controls, and Play Through
9. freeze each block product before grading that block
10. emit the complete acceptance artifact set and deterministic hashes
11. prevent an ordinary second untouched-holdout execution

## Stop state

`NOT_READY_TO_OPEN_2025`

**2025 HOLDOUT HAS NOT BEEN OPENED.**
