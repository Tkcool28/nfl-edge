# Task05F Market Evaluation Layer V1 — Repo-Native Validation Evidence (Remediated)

Branch: `feat/task05f-market-evaluator-v1`
Starting HEAD (this commit): `86db7bbaf0d745668261238eb425147984560b60`
Base lineage (main): `7824f1de54d039874abf96b1f97ff135018b34cf`
Production `/root/nfl-edge`: `main @ 7824f1de54d039874abf96b1f97ff135018b34cf` (untouched)

## Scope of this remediation

1. **Reliability/support contract made real**:
   - out-of-support distance computed from PRIOR-block support envelopes (was hard-disabled at 0.0);
   - chronological stability evidence computed from PRIOR blocks (was an unchanging `True`);
   - `EvaluatorState.uncertainty` default changed `0.0` → `None`; every family now receives its own
     block-bootstrap calibration radius (no fake perfect certainty).
2. Mechanical `exact_avg` fail-closed fix (from the prior validation commit) remains intact.
3. No methodology retune: evaluator families, shrinkage formulas, logistic features, point-market
   families, selection tolerances, probability clipping, shopping semantics, Pinnacle role are
   unchanged. No selectors, no staking engine, no football-model retuning.

## Development universe (resolved)

- Evaluator training observation seasons: **2020–2024 only**.
- Evaluator scored-OOS seasons: **2020–2024 only**.
- 2018–2019 **never enter evaluator fitting or scoring** (runner lazy-filter `season.is_in(DEV)`,
  DEV=[2020..2024] on every model input before materialization; present only inside frozen upstream artifacts).
- No scored evaluator row outside 2020–2024 (verified max season = 2024).

## Football-model unchanged proof

`git diff 7824f1de..HEAD` and this worktree's diff modify only Task05F `value/` files. No file under
`src/nfl_edge/models/` is touched. `test_frozen_football_models_do_not_import_market_evaluator_layer` passes.

## 2025 firewall proof

Evaluator functions raise RuntimeError on `season == 2025`; runner uses lazy 2020–2024 predicates;
verified all 34,994 materialized evaluator rows have max season == 2024. No 2025 outcome/ROI/market consumed.

## Test results

```
tests/value/  ->  34 passed (15 original + new reliability/support regression suite)
```

Relevant market-edge compatibility contracts re-run: pass except the known pre-existing stale
`test_production_head_untouched` (hard-codes obsolete prod HEAD `b805534`; prod is `main @ 7824f1de`).
Not a remediation regression; left unmodified.

## Determinism proof

Two independent chronological runs → `scorecard.json` and `provenance.json` byte-identical.
scorecard.json SHA-256: `fdd0116979d9c5b3305f3ef22d2ee8ce3de6a0f884ee202750b868f3cf713f03` (both runs).

## Selection (preregistered rule, unchanged after remediation)

- Moneyline: **global_shrinkage** (Brier ~0.2069)
- Spread: **calibrated_normal** (Brier ~0.2503)
- Totals: **calibrated_normal** (Brier ~0.2508)

## Signal interpretation

- Moneyline global_shrinkage: Brier 0.2069, AUC 0.7405 — demonstrates incremental discrimination over Pinnacle (Brier 0.2106, AUC 0.729).
- Spread calibrated_normal: Brier 0.2503, AUC ~0.493 — **calibrated probability translation, weak/no demonstrated global discrimination**. Not promoted as strong wagering signal.
- Totals calibrated_normal: Brier 0.2508, AUC ~0.500 — same characterization.

See `reliability_support_validation.md` for the full reliability formula, support-distance formula,
support features by market, stability rule, uncertainty definition, reliability/support distributions,
and unsupported reason counts.
