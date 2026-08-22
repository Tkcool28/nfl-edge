# Task05F Product Simulation V2 — Validation Summary

**Verdict:** `VALID_DETERMINISTIC_DIAGNOSTIC / STRUCTURAL_CONTRACTS_PASS / PERFORMANCE_NOT_PROMOTIONAL`

**Result label:** `OBSERVATIONAL_ONLY_NOT_TUNED`

This report records the single designated 2020–2024 diagnostic replay of Selector V3.1 plus evaluator-unit Staking V2. It is not an acceptance test for selector profitability and it may not be used to tune selector rules, unit formulas, risk-style bankroll fractions, Play Through, evaluator probabilities, or market capabilities.

Selector V3.1 was designed after Selector V1/V2 development outcomes had already been observed. Therefore 2020–2024 cannot provide clean promotion evidence for V3.1. Sealed 2025 remains the next clean selector/staking outcome evidence after independent review and backend freeze.

---

## 1. Designated execution

- PR: `#20` — `feat/task05f-evaluator-rebuild-v1`
- Designated branch head: `9235f63c999408878e1f7918d87f03aaa2d14ed2`
- GitHub PR merge-test SHA executed by Actions: `44deee2b593db2ad25ae976d5389e8928cc9b04e`
- Clean pre-score contract SHA: `d9fa2e0e75c3d17be927e3a6f80ecbe4abf08ec8`
- Actions run: `32560871713`
- Actions job: `97002092015`
- Conclusion: `success`
- Value-layer tests: **219 passed in 3.43s**
- Two complete Product V2 simulations were run and compared with `diff -qr`; outputs were identical.
- Hard product contracts: `PASS`
- Evidence artifact ID: `9472814656`
- Evidence artifact ZIP digest: `sha256:61014841417d7a5596bcd0f6d8bd0aa6385ee3eb402d9e83b1f1b49956d55a04`

A prior push-only attempt at `c9d2b70b64ed35893cc53a0fff2afd3c0b4d2982` was not observable through the connector and was classified before result inspection as:

`UNOBSERVABLE_INFRA_ATTEMPT_NOT_EVIDENCE`

It is not evidence and is not used in this report.

---

## 2. Frozen contracts used

Product V2 used only the preregistered/frozen downstream contracts:

- Candidate table: `config/task05f_candidate_table_v1.yaml`
  - evidence SHA-256: `801b3826f30462b082d606de24a601fb9b21b2af97328791d1045d997a812aa6`
- Selector V3.1: `config/task05f_selectors_v3_1_product_prereg.yaml`
  - evidence SHA-256: `7fbc8f4f8e7b01efcde86d2c5a74b551590aaf218a1741cff8a16c1719bacf71`
- Staking V2: `config/task05f_staking_v2_units_prereg.yaml`
  - evidence SHA-256: `7252e330db5df33594255ab199d0796d53019501ed6aba3ff291b922a188cc91`
- Product simulation V2: `config/task05f_product_simulation_v2.yaml`
  - evidence SHA-256: `d1a4b0dac701cb4b2f21f55aa5a11e72bcea43306660f5cff8c8f13627de21fe`

Product Simulation V1 / Kelly-Flat product replay is explicitly superseded and is not evidence.

---

## 3. Reproduction and leakage proof

The designated run reproduced the accepted candidate interface before any selector outcome join:

- candidate rows: **8,448**
- unique logical candidate payload hash before selection: `8a94ea81b327392f66e1f85c95c04693701e3e91ad51ba9d4e046aa183758527`
- logical candidate payload hash after selection: `8a94ea81b327392f66e1f85c95c04693701e3e91ad51ba9d4e046aa183758527`
- candidate rows immutable: **true**
- outcome fields in production candidate table: **none**
- selections and evaluator-owned unit ratings frozen before historical outcome sidecar join: **true**
- development seasons: **2020–2024**
- sealed season: **2025**
- season-week slates: **109**

All non-null featured card candidate IDs were distinct under the preregistered V3.1 featured-card contract.

---

## 4. Selector coverage and composition

| Card | Plays | No-play weeks | Moneyline | Spread | Total | VALUE | PLAYABLE |
|---|---:|---:|---:|---:|---:|---:|---:|
| High Hit Rate | 57 | 52 | 30 | 27 | 0 | 35 | 22 |
| Balanced | 55 | 54 | 22 | 33 | 0 | 43 | 12 |
| Value | 52 | 57 | 0 | 52 | 0 | 52 | 0 |

Every selected wager was `MEDIUM` reliability. No total reached a primary card because the frozen Phase F totals population has no HIGH/MEDIUM rows.

Across 109 slates:

- 49 slates had no featured wager
- 4 had one
- 8 had two
- 48 had all three
- 60 / 109 slates had at least one featured wager
- mean featured wagers per slate: approximately **1.50**

This is coverage description only, not a target.

---

## 5. Evaluator-assigned units

The V2 unit engine behaved inside its frozen bounds.

### PLAYABLE

- n = **34**
- minimum = **0.5096u**
- mean = **0.7061u**
- maximum = **0.9582u**
- required range = **0.50u to 1.00u**

This demonstrates the intended Play Through behavior: a wager remains stakeable even where Kelly would be nonpositive, but stake size shrinks as price moves toward the Play Through limit.

### VALUE

- n = **130**
- minimum = **1.0008u**
- mean = **1.2639u**
- maximum = **1.4387u**
- required range = **1.00u to 2.00u**

No selected historical Value reached the theoretical 2u maximum.

### Mean units by card

| Card | n | Mean units | Min | Max |
|---|---:|---:|---:|---:|
| High Hit Rate | 57 | 1.0141u | 0.5096u | 1.3948u |
| Balanced | 55 | 1.1402u | 0.5458u | 1.3864u |
| Value | 52 | 1.3039u | 1.0569u | 1.4387u |

Unit ratings are evaluator-owned and identical regardless of user risk style.

---

## 6. Historical selector outcomes

**All results in this section are `OBSERVATIONAL_ONLY_NOT_TUNED`.**

Flat one-unit outcome accounting across the selected wagers gives:

| Card | W-L-P | Hit rate ex-push | Flat 1u ROI |
|---|---:|---:|---:|
| High Hit Rate | 31-26-0 | **54.39%** | **-13.31%** |
| Balanced | 30-25-0 | **54.55%** | **-0.77%** |
| Value | 26-25-1 | **50.98%** | **-2.43%** |
| All featured selections | 87-76-1 | **53.37%** | **-5.66%** |

These outcomes do not modify any selector or staking rule.

### Market split diagnostics

Also `OBSERVATIONAL_ONLY_NOT_TUNED`:

| Card / market | n | Hit rate ex-push | Flat 1u ROI |
|---|---:|---:|---:|
| Balanced — spread | 33 | 63.64% | +22.07% |
| Balanced — moneyline | 22 | 40.91% | -35.04% |
| High Hit Rate — moneyline | 30 | 60.00% | -17.25% |
| High Hit Rate — spread | 27 | 48.15% | -8.93% |
| Value — spread | 52 | 50.98% | -2.43% |

These splits are not permission to create market-specific selector rules. In particular, no ML/spread restriction, threshold, or re-ranking is introduced from this table.

---

## 7. Five user risk styles

Each profile began with a $100 bankroll. The same 164 evaluator-rated featured wagers were used for every profile; only the dollar value of a unit changed.

### Combined featured-card portfolio

| Risk style | End bankroll | Return | Max drawdown | Minimum bankroll | Max one-slate exposure | Configured cap | Total staked |
|---|---:|---:|---:|---:|---:|---:|---:|
| Cautious | $94.33 | -5.67% | 12.29% | $91.94 | 2.11% | 3% | $92.99 |
| Conservative | $91.47 | -8.53% | 17.91% | $88.06 | 3.15% | 5% | $138.41 |
| Standard | $88.50 | -11.50% | 23.24% | $84.20 | 4.21% | 7% | $183.27 |
| Aggressive | $82.66 | -17.34% | 32.94% | $76.91 | 6.30% | 10% | $270.66 |
| Very Aggressive | $70.76 | -29.24% | 49.28% | $63.26 | 10.49% | 15% | $435.77 |

All configured exposure limits held. The 5% absolute single-wager cap also passed the hard contract suite.

The progression is directionally sensible for the intended UX: choosing a larger risk style does not improve wager quality; it only magnifies both gains and losses. In this negative historical sample, higher styles produced progressively larger bankroll damage and drawdown. This is a product-risk observation, not a parameter-selection criterion.

---

## 8. Per-card bankroll diagnostic at STANDARD

Starting from $100 independently for each card:

| Card | End bankroll | Return | Max drawdown | Total staked |
|---|---:|---:|---:|---:|
| High Hit Rate | $91.41 | -8.59% | 10.46% | $55.70 |
| Balanced | $98.68 | -1.32% | 11.36% | $63.64 |
| Value | $98.31 | -1.69% | 7.46% | $67.41 |

Again, these are diagnostic outcomes only.

---

## 9. Evidence file hashes

The accepted first deterministic output set has these SHA-256 hashes:

- `candidate_reproduction.json`: `5aa4454f309a61f705a0f9279da1fcbb0e148fa0753c72a7aa6a076b7d489f86`
- `diagnostics.json`: `a0ddf495d696e7eed6610ab5fc43ff35e826f5c293bc4d3d63787c4057045593`
- `per_card_bankroll.json`: `40230bd98b601c5898c46c478c0864400e45942df43a861b4db4ba8b8cad7b26`
- `portfolio_bankroll.json`: `c430b1cbc11d3e8ad7f41e04f3227fece23c0b3de7fe62b6d9b9c4d2c6c21c7b`
- `provenance.json`: `db4f5dcff720ed5e567c3387ca899d07715bc2dd5795e081c189314f7bf8f5df`
- `scorecard.json`: `0463b16e51636071a6d1d60193633b2834619f9653ad77f58daf9d6f72b0a5a2`
- `selector_picks.json`: `b4337797490305fdbcc883810ff98de72ce1b22450f27c962a63bba2714986f4`
- `stake_ledger.csv`: `76d74c1b18faefed73fefe88bd3d7a1fe162709161e0f1cbe83ea2f48ad33b26`
- `unit_assignments.csv`: `5fe8729fd6d08852297dd7fcc6269b20fd7d0bfc7b53302622024930aa4e2186`

---

## 10. Interpretation

### What passed

The end-to-end architecture is mechanically coherent:

- accepted 8,448-row candidate state reproduced exactly;
- no result leakage into selection or unit assignment;
- V3.1 selectors were deterministic;
- featured candidate identities followed the preregistered distinctness contract;
- PLAYABLE received a conservative nonzero 0.5–1.0u stake rather than being stranded at Kelly zero;
- VALUE received 1–2 evaluator-controlled units;
- the user risk style changed dollar scale but never wager quality or unit rating;
- the 5% per-wager ceiling held;
- all five slate exposure caps held;
- 2025 remained sealed;
- two executions were byte-for-byte identical.

### What did not pass as performance proof

2020–2024 does not demonstrate positive profitability for the complete V3.1 product card. The Standard combined portfolio lost 11.50%, and the flat one-unit selected set was -5.66% ROI.

That finding is recorded rather than hidden, but it does not trigger retrospective rule changes because this dataset is development-contaminated for V3.1 and the simulation was preregistered as diagnostic only.

### What happens next

Do **not** tune Selector V3.1, Staking V2, the five risk styles, exposure caps, Play Through, or evaluator thresholds from this result.

Next steps are:

1. create the backend selector/staking/interface freeze and exact hash manifest;
2. run independent architecture/diff/evidence review;
3. correct implementation defects only if review finds them;
4. only after the backend contract is frozen, open sealed 2025 once for the clean week-by-week product evaluation.

The key 2025 question remains whether an ordinary bettor would have received a useful, honest, understandable card with sensible risk control—not whether development ROI can be made green after the fact.
