# Task05F Market Evaluation Layer V1 — Repo-Native Validation Evidence (orientation-fix run)

Branch: `feat/task05f-market-evaluator-v1`
Starting HEAD (this commit): `cc8c6945be80a478d67ef20a993496145a8a4715`
Base lineage (main): `7824f1de54d039874abf96b1f97ff135018b34cf`
Production `/root/nfl-edge`: `main @ 7824f1de54d039874abf96b1f97ff135018b34cf` (untouched)

## Scope of this commit

1. **Support-coordinate consistency fix**:
   - Moneyline `avg_pin_gap` now uses the **signed** coordinate `exact_avg_selected_side - pinnacle_no_vig_selected` in both historical envelope fitting and live/manual evaluation (was signed in fitting but `abs()` in evaluation — the mismatch could falsely label historically-supported negative disagreement as out-of-support).
   - Point-market support uses an **orientation-invariant** `delta_magnitude = abs(delta)` for spread and totals, so mirrored sides (away/under) share one support space with the canonical HOME/OVER orientation. Probability math still uses selected-side **signed** delta (Normal-CDF / calibrated-Normal / strong-logistic unchanged).
   - Support feature renamed `delta` → `delta_magnitude` for point markets.
2. All prior reliability/support fixes preserved (fail-closed out-of-support, prior-block stability, uncertainty default None, exact_avg fail-closed, 2025 firewall).
3. No methodology change: evaluator families, shrinkage formulas, selection tolerances, probability clipping, shopping, Pinnacle role unchanged. No selectors, no staking, no football-model retuning, no 2025 opened.

## Development universe (resolved)

- Evaluator training observation seasons: **2020–2024 only**.
- Evaluator scored-OOS seasons: **2020–2024 only**.
- 2018–2019 never enter evaluator fitting or scoring (runner lazy-filters `season.is_in(DEV)`, DEV=[2020..2024]).
- No scored evaluator row outside 2020–2024 (max season = 2024 verified).

## Football-model unchanged proof

`git diff 7824f1de..HEAD` and this worktree's diff modify only Task05F `value/` files. No file under
`src/nfl_edge/models/` touched. `test_frozen_football_models_do_not_import_market_evaluator_layer` passes.

## 2025 firewall proof

Evaluator functions raise RuntimeError on `season == 2025`; runner uses lazy 2020–2024 predicates.
Verified all 34,994 materialized rows max season == 2024.

## Test results

```
tests/value/  ->  42 passed (incl. new signed-gap + delta-magnitude invariance tests)
```

Relevant market-edge compatibility contracts re-run: pass except the known pre-existing stale
`test_production_head_untouched` (hard-codes obsolete prod HEAD `b805534`; prod is `main @ 7824f1de`).
Not a task regression; left unmodified.

## Determinism proof

Two independent chronological runs → `scorecard.json` and `provenance.json` byte-identical.
scorecard.json SHA-256: `16854c0cd261c321b08f388e07910a672df72f166c117587bf7a7d0a385994` (both runs).
provenance.json SHA-256: `e88d032502b0cbe7a0687b813d8ee22616343913c81cd6d8b450a0e892c0e3a7`.

## Selection (preregistered rule, unchanged after orientation fix)

- Moneyline: **global_shrinkage** (Brier ~0.2071)
- Spread: **calibrated_normal** (Brier ~0.2503)
- Totals: **calibrated_normal** (Brier ~0.2508)

## Signal interpretation

- Moneyline global_shrinkage: Brier 0.2071, AUC 0.740 — demonstrates incremental discrimination over Pinnacle (Brier 0.2106, AUC 0.729).
- Spread calibrated_normal: Brier 0.2503, AUC ~0.493 — calibrated translation, weak/no demonstrated global discrimination.
- Totals calibrated_normal: Brier 0.2508, AUC ~0.500 — same.

See `reliability_support_validation.md` for full reliability/support formulas, coordinate definitions,
stability rule, uncertainty definition, distributions, and unsupported reason counts.