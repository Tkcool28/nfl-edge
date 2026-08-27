# Task05G Value ML Nonmature Singleton Fail-Safe V1 — Preregistration

Status: **FROZEN BEFORE REPLAY / 2025 SEALED**

This is a bounded retrospective development experiment motivated by the forensic result in `reports/task05g/value_ml_2023_state_depth_audit_v1_review.md`.

All 2020-2024 outcomes are exposed. This replay cannot create independent validation. 2025 remains sealed.

## 1. Baseline

Baseline user-facing Value policy is the leading stack already established before this test:

- strict frozen Value candidate families only;
- Task05F exact-offer `VALUE` and expected value > 0;
- ML frontier and causal ML trust constants unchanged;
- Pareto spread frontier from PR #45;
- non-GREEN singleton spread fail-safe from PR #47;
- no totals.

No HHR or Balanced rule is changed.

## 2. Frozen ML evidence labels

Reuse the existing causal ML trust machinery exactly:

- reset trust = 0.50;
- pseudo-count = 8;
- AMBER cannot activate until 3 settled prior ML-frontier observations and requires trust < 0.50;
- RED cannot activate until 8 observations and requires trust < 0.25.

For this test only, use the already-audited descriptive label:

- `COLD`: prior settled ML-frontier observation count `< 3`;
- `MATURE_GREEN`: count `>= 3` and existing state GREEN;
- `AMBER`: existing state AMBER;
- `RED`: existing state RED.

`COLD` adds no new numeric threshold; it merely names the existing pre-AMBER minimum-N interval.

## 3. Primary fail-safe

Starting from the baseline Value card, suppress an ML headline **only if all three conditions are true before the block**:

1. ML evidence status is `COLD` or `AMBER`;
2. the strict ML Value candidate depth in that block is exactly 1;
3. there is no valid Pareto spread frontier in that block.

Then:

```text
VALUE = PASS
```

No ML or spread replacement is allowed for a suppressed play.

Everything else is unchanged:

- `MATURE_GREEN` singleton ML remains eligible;
- COLD/AMBER competitive ML remains eligible;
- COLD/AMBER singleton ML with a valid spread frontier is not automatically suppressed;
- RED behavior remains the existing frozen ML state-machine behavior and is not altered by this test;
- no trust, EV, price, q, or candidate-family threshold is tuned.

## 4. Required invariants

The replay must prove:

- 2025 absent from every input/output;
- no football model, evaluator, confidence mapping, candidate family, HHR, Balanced, or spread selector change;
- the only user-facing baseline plays removed are ML plays satisfying the exact three-condition rule;
- no new play is created;
- no suppressed ML play is backfilled by spread or another ML candidate;
- all unaffected baseline candidate identities are byte-for-byte identical;
- deterministic double replay.

Any violation hard-fails.

## 5. Required reporting

Report baseline versus fail-safe by season, 2020-2022, 2023-2024, and 2020-2024:

- plays / coverage;
- W/L/P;
- hit rate;
- flat 1u ROI and cumulative units;
- max losing streak;
- ML/spread mix;
- exact removed blocks and outcomes.

Also report the removed ML plays with:

- evidence status;
- prior n and trust;
- ML candidate depth;
- spread frontier presence/depth;
- odds;
- model q;
- break-even probability;
- model-price gap;
- Task05F evaluated edge / expected value;
- settlement / realized units.

## 6. Interpretation guard

The primary question is whether this narrow rule selectively removes the exposed `0-5` uncorroborated nonmature singleton cell **without sacrificing mature singleton ML or healthy-season Value volume**.

This test may not broaden the condition after seeing results. No threshold grid, season-specific exception, retrospective fixed-rank rule, or 2025 access is permitted.

A favorable retrospective result is still only a final development candidate. Production promotion requires the later sealed acceptance phase.