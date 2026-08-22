# Task05F Play Through V1.1 — 1.5pp Product-Policy Evidence

Status: **VALID EXECUTION / STRUCTURALLY ACCEPTED PRODUCT POLICY / NOT A VALUE SIGNAL**

Play Through V1.1 is strictly downstream of the locked Task05F evaluator and accepted Phase F reliability/uncertainty/staking-probability layer. It does not change frozen football models, evaluator probability, strict expected value, strict `VALUE`, reliability, uncertainty, support, or staking probability.

## Product decision and preregistration

The product maximum was changed from the completed V1 evidence policy of 1.0 percentage point of break-even tolerance to **1.5 percentage points** after product review. The decision was preregistered before any valid V1.1 historical scoring:

- preregistration: `config/task05f_play_through_v1_1_prereg.yaml`
- preregistration commit: `869418ae7af22c0e02bb3169187cac5e1cb24f48`
- maximum concession: `0.015`
- same global formula for ML / spread / total
- same Phase F reliability × uncertainty confidence multiplier
- no ROI input
- no price/disagreement bucket input
- no market-specific tolerance
- no selector scoring
- 2025 sealed

V1 (1.0pp) remains immutable prior evidence. V1.1 was not selected by scanning 1.25/1.5/1.75/2.0pp historical alternatives.

## Invalid mechanical attempt

Workflow `32551481010` on feature commit `15434e6a7deb2421283ca6dcc7575e93178e15e7` failed while writing provenance because a relative config path was passed to `Path.relative_to()` against an absolute repository root. Its partial historical outputs were not accepted or used for a decision.

The correction normalized the config path at runner entry only. It did not change Play Through math, status rules, evaluator fields, reliability, uncertainty, or staking probability.

A separate automatic duplicate run triggered by the selector-preregistration push was classified `DUPLICATE_REPRODUCTION_NOT_EVIDENCE` before artifact/result inspection (PR audit comment `5377854746`).

## Accepted execution

- feature commit: `f37651369b1510e5809dcdf61bf71449fd92dbeb`
- PR merge-test SHA recorded by Actions: `1f21832d59e46696bcce444f493b8a6442c59291`
- workflow run: `32551802858`
- artifact ID: `9470345629`
- artifact ZIP digest: `sha256:ae577d7a94170a6267cfeb0abd30e5d8ed3123c06841c73d1983f2070da88366`
- value-layer tests: **106 passed**
- evaluator-only scope guard: PASS
- 2025 firewall: PASS
- V1.1 preregistration guard: PASS
- two complete chronological executions: PASS
- deterministic output comparison: PASS
- upstream evaluator / Phase F reproduction: PASS
- locked rows: **8,448**

Deterministic hashes:

- `full_board.parquet`: `a3f7c8ff42e61ba85501b42a8aa964728aaa899c02b826bd330589b696c472b7`
- `scorecard.json`: `02ed8fd68f9b387bc63526f68c07ca3a7c18699a3d0af6dcda4c7eccdecf245c`
- `status_by_reliability.csv`: `effb700cce817c9defc65607adcb6a5a443532199e543bb6c15083a903be021b`

## Hard reproduction gates

V1.1 reproduced all accepted upstream fields exactly:

- Phase F rows: 8,448
- V1.1 rows: 8,448
- preserved rows equal: true
- strict Value labels unchanged: true
- negative EV never labeled Value: true
- PLAYABLE never exceeds preregistered price envelope: true
- immutable payload SHA before/after:
  `5560633ed5836344c68145d3f29dbfc005c3cf59eafa3576ad0297860b3389d2`

## Actual confidence-scaled concession

The configured 1.5pp is a maximum, not a blanket allowance. Historical Phase F confidence scaled it down materially:

| Market | Mean confidence | Mean break-even concession | Maximum observed concession |
|---|---:|---:|---:|
| Moneyline | 0.2537 | **0.381 pp** | **0.704 pp** |
| Spread | 0.3441 | **0.516 pp** | **1.140 pp** |
| Total | 0.1091 | **0.164 pp** | **0.372 pp** |

No historical row received the full 1.5pp concession.

## Status counts

| Market | VALUE | PLAYABLE | LEAN | PASS |
|---|---:|---:|---:|---:|
| Moneyline | 754 | **111** | 1,337 | 614 |
| Spread | 385 | **194** | 1,969 | 268 |
| Total | 544 | **54** | 1,944 | 274 |

Relative to completed V1 (1.0pp), V1.1 adds 45 ML, 70 spread, and 16 total historical `PLAYABLE` rows. This is a product-coverage observation only, not a training target.

## Reliability cross-tab relevant to later primary selectors

The separately preregistered selector contract permits only `HIGH` / `MEDIUM` reliability on the three primary cards. Under that already-frozen rule:

- ML strict `VALUE`: **153 MEDIUM**, 0 HIGH
- ML `PLAYABLE`: **89 MEDIUM**, 0 HIGH
- Spread strict `VALUE`: **202 MEDIUM**, 0 HIGH
- Spread `PLAYABLE`: **161 MEDIUM + 11 HIGH = 172**
- Totals: **0 HIGH/MEDIUM**, therefore explorer-only under the current selector contract

LOW rows remain visible in the game explorer but cannot populate High Hit Rate, Balanced, or Value.

## Historical realized ROI diagnostics — OBSERVATIONAL_ONLY_NOT_TUNED

These diagnostics are required disclosure and are **not** used to alter V1.1:

| Market | PLAYABLE n | PLAYABLE realized ROI |
|---|---:|---:|
| Moneyline | 111 | **-1.08%** |
| Spread | 194 | **-12.66%** |
| Total | 54 | **-13.10%** |

Primary-selector-eligible (`HIGH`/`MEDIUM`) PLAYABLE observations:

- ML: 89 rows, realized ROI **+6.10%**
- Spread: 172 rows, realized ROI **-12.60%**
- Total: 0 rows

No market-specific Play Through rule, threshold, or exclusion is introduced from these results. In particular, the poor historical spread PLAYABLE diagnostic is not used to retune the global 1.5pp product policy after seeing outcomes.

Strict `VALUE` continues to be defined solely by locked evaluator `EV > 0`. Play Through is a current-price/actionability presentation policy, not a new expected-value estimator.

## Decision

**Play Through V1.1 is structurally accepted as the frozen 1.5pp confidence-scaled product policy.**

It is accepted because it:

1. preserves every upstream probability / EV / Value / reliability / staking field;
2. applies one preregistered global formula across markets;
3. grants only confidence-scaled price tolerance, with no historical ROI input;
4. never relabels negative EV as Value;
5. is deterministic;
6. keeps 2025 sealed;
7. provides the game explorer and High Hit Rate selector with a modest `PLAYABLE` state without manufacturing strict Value.

Historical PLAYABLE profitability is not an acceptance claim and remains `OBSERVATIONAL_ONLY_NOT_TUNED`.

Next: build the common candidate-table contract, then implement the already-preregistered High Hit Rate / Balanced / Value selectors without changing V1.1 from selector outcomes.
