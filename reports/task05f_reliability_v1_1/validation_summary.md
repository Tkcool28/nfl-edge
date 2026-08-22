# Task05F Phase F Reliability / Uncertainty V1.1 — Validation Summary

Status: **ACCEPTED AS POST-PROBABILITY RISK-SIZING LAYER / NOT A VALUE SELECTOR**

This report freezes the first valid historical scoring of the preregistered Task05F reliability, uncertainty, and conservative staking-probability layer after the exact-offer point-market staking-anchor correction.

## Locked upstream evaluator

- Moneyline probability architecture: `ml_v4`
- Spread probability architecture: `spread_v3`
- Total probability architecture: `total_v3`
- Locked evaluator rows: **8,448**
- Development seasons: **2020–2024**
- Sealed season: **2025**
- Strict Value remains: **evaluator `expected_value > 0`**

Phase F is downstream of those probabilities. It is not allowed to alter fair probability, fair price, evaluator EV, strict Value, or support.

## Exact-offer correction before valid scoring

The initial Phase F point-market staking anchor incorrectly treated Pinnacle probability at Pinnacle's own spread/total line as if it represented a possibly different actionable DK/FD line. That run was invalidated before its historical Phase F result was accepted.

V1.1 translates the V3 Pinnacle line + no-vig probability + prior-only score scale to the **same exact actionable wager line** before any risk shrinkage. Same-line point sides complement conditional on non-push; independently shopped different lines are not forced to complement.

The superseded Phase F v1 is not acceptance evidence.

## GitHub Actions proof

- Feature commit: `f213f02b443c85040defa618c91f9b098f88ef34`
- Workflow run: `32549390727`
- Artifact ID: `9469653744`
- Artifact ZIP digest: `sha256:544703bcc9519c330c4e85a32a30e8dced826fbdd439fdef92033e2e26db9339`
- Value-layer tests: **96 passed**
- Evaluator-only scope guard: **PASS**
- Sealed-2025 firewall: **PASS**
- Exact-offer staking-anchor guard: **PASS**
- Two complete corrected chronological Phase F runs: **PASS**
- Deterministic output comparison: **PASS**
- Locked evaluator immutable reproduction: **PASS**

Immutable payload SHA-256 before and after Phase F:

`0f5fa7115392c9b6262ac29df675629fb4623c9fb0208847ae9006c9a55c75fd`

The following remained unchanged on all 8,448 rows:

- `p_win`
- `p_push`
- `p_loss`
- `actionable_probability`
- `fair_price_american`
- `expected_value`
- `strict_positive_value`
- `supported`

## Reliability evidence

| Market | Supported | Final HIGH | Final MEDIUM | Final LOW | Mean uncertainty radius |
|---|---:|---:|---:|---:|---:|
| Moneyline | 2,202 | 0 | 747 | 1,455 | 0.04075 |
| Spread | 2,548 | 32 | 1,618 | 898 | 0.03903 |
| Total | 2,542 | 0 | 0 | 2,542 | 0.06526 |

Interpretation:

- **Moneyline:** useful but not high-confidence uncertainty evidence; later selector policy may use MEDIUM rows and should treat LOW conservatively.
- **Spread:** strongest reliability profile of the three markets; a small HIGH set emerges and most supported rows become MEDIUM.
- **Totals:** the uncertainty layer correctly refuses to promote the supported totals board beyond LOW. Totals may remain visible in the explorer but should not become a primary recommended wager under a future MEDIUM-or-better selector requirement.

## Staking-probability diagnostics

These are `OBSERVATIONAL_ONLY_NOT_TUNED`. They do not define Value and are not a selector target.

| Market | Staking +EV rows | Realized ROI | Staking nonpositive rows | Realized ROI |
|---|---:|---:|---:|---:|
| Moneyline | 755 | -4.72% | 1,447 | -4.73% |
| Spread | 161 | -2.73% | 2,387 | -3.84% |
| Total | 59 | -16.76% | 2,483 | -3.41% |

The staking probability therefore **must not be treated as a new value-finding model or eligibility rule**. Its purpose is narrower: once downstream policy has selected an otherwise eligible wager, it supplies a reliability/uncertainty-haircut probability for bankroll sizing.

No Kelly fraction, selector threshold, Play Through threshold, or market bucket is tuned from these figures.

## Frozen Task05E evidence remains external

The locked evaluator's exact-offer preservation report remains unchanged by Phase F. In particular, the frozen `SPREAD_0_4_DISCOVERY_UNION` baseline remains positive overall, and the locked evaluator's supported subset remains positive. Phase F does not redefine or optimize that historical evidence.

## Acceptance decision

**PHASE_F_RELIABILITY_UNCERTAINTY_V1_1_ACCEPTED**

Accepted semantics:

1. `actionable_probability` remains the best evaluator probability and drives fair price / strict EV.
2. `reliability` and `uncertainty` are separate evidence-quality outputs.
3. `staking_probability` is a downstream risk-sizing probability only.
4. `staking_expected_value` is diagnostic and cannot create or relabel `VALUE`.
5. Unsupported wagers cannot become recommended wagers.
6. 2025 remains sealed.

## Next phase

Proceed to the common candidate/product-policy layer. Freeze Play Through and selector-facing status semantics **before** historical selector scoring. Do not tune them for coverage or ROI.
