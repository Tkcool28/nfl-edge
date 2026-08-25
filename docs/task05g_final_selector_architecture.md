# Task05G Final Selector Architecture

Status: **ARCHITECTURE FROZEN FOR FINAL INTEGRATION / 2025 SEALED**

This document is the selector source of truth for the final Task05G integration. It supersedes earlier experimental selector semantics where Hit Rate, Balanced, and Value shared too much ranking/economic logic.

The three headline cards consume the same evidence table but **must use three separate protocols**. They are not variants of one generic score.

## 1. Product contract

NFL EDGE presents three weekly headline slots:

1. **Hit Rate** — highest trustworthy chance to cash. ROI/EV is not the objective.
2. **Balanced** — highest trustworthy probability subject to a genuinely reasonable actionable price. This is the primary casual-facing card.
3. **Value** — a strict +EV exact offer from a historically supported football-model family. Value may be absent.

For an 18-week season this means 18 Hit Rate slots, 18 Balanced slots, and 18 Value slots (54 possible lane-slots). Twice-daily production refreshes may change the current recommendation or price inside a weekly slot; refreshes do not create additional season slots.

Desired product behavior is high Hit Rate and Balanced availability. Value coverage is descriptive only and may legitimately be sparse. Coverage must never be manufactured by outcome-driven threshold loosening.

## 2. Hard layer separation

```text
FOOTBALL MODELS (no sportsbook inputs)
    QB-Elo
    XGBoost
    Expected Margin
    [Totals only when validated]
        |
        v
MODEL-CONFIDENCE LAYER
    ML: calibrated QB-Elo/XGBoost football confidence
    Spread: Spread Confidence V3
        |
        +--------------------+
        |                    |
        v                    v
MARKET NORMALIZATION     TASK05F EVALUATION
DK / FD / Pinnacle       exact-offer probability / EV / support
        |                    |
        +---------+----------+
                  v
        COMMON CANDIDATE EVIDENCE TABLE
                  |
        +---------+----------+----------+
        |                    |          |
        v                    v          v
  HIT RATE PROTOCOL   BALANCED PROTOCOL  VALUE PROTOCOL
```

A shared evidence table does **not** imply shared selector semantics.

### Required separation

- Football-model confidence remains distinct from market/evaluator probability.
- Pinnacle may corroborate selector trust downstream; it may not become a football-model feature.
- Exact DK/FD price determines actionability/economics; price may not rewrite football confidence.
- HHR and Balanced must not inherit Value status/EV as hidden primary ranking logic.
- Value must not inherit HHR/Balanced hit-rate objectives or forced coverage.

## 3. Common evidence contract

Every selector may read the same candidate evidence, including:

- candidate/game/market/side identity
- exact best actionable DK/FD offer
- Pinnacle benchmark / no-vig probability when applicable
- raw football-model outputs
- `model_confidence_probability`
- ML QB-Elo and XGBoost selected-side probabilities
- Spread Confidence V3 probability
- Task05F actionable/evaluated probability
- break-even probability
- exact-offer expected value
- model-price gap / consensus diagnostics
- reliability / uncertainty / support
- price status (`VALUE`, `PLAYABLE`, `LEAN`, `PASS`, `UNSUPPORTED`)

The presence of a field does not authorize every selector to use it as an objective.

## 4. Protocol A — Hit Rate

### Product question

> Which supported wager has the highest trustworthy probability of cashing?

### Objective

**Maximize trustworthy hit probability.**

ROI, expected value, and Value/Playable status are reporting/economic diagnostics only. They do not define the HHR winner.

### Candidate universe

V1 headline-eligible markets:

- moneyline
- spread with Spread Confidence V3 support

Totals remain excluded until a totals football edge earns headline eligibility.

Candidate must have:

- supported football/model-confidence evidence
- sufficient historical/model-confidence support
- exact actionable DK/FD offer
- non-UNSUPPORTED reliability state
- price inside the frozen HHR price-sanity band

HHR must **not** require:

- strict positive EV
- `VALUE` status
- `PLAYABLE` status
- positive model-price gap
- positive historical ROI

`PASS`/`LEAN` caused only by exact-offer economics must not automatically disqualify an otherwise supported HHR candidate. `UNSUPPORTED` still fails closed.

### ML ranking trust

Frozen architecture uses model confidence as the primary signal and Pinnacle only as an extreme-confidence corroborator.

Primary HHR ML trust candidate:

```text
excess_over_pinnacle = max(model_confidence - pinnacle_no_vig, 0)
hhr_trust = model_confidence - 0.50 * excess_over_pinnacle
```

Properties:

- if model confidence is at or below Pinnacle, the model is unchanged;
- if model confidence outruns Pinnacle, only half of the excess is pulled back;
- this is a ranking trust score, not a new calibrated probability;
- Pinnacle does not replace the football models.

For spread, `hhr_trust = Spread Confidence V3 probability`.

### Ranking order

1. HHR trust
2. model confidence
3. reliability/support
4. deterministic exact-offer/book/candidate tie-break

Expected value must not appear before these fields and should not be needed as a tie-break.

### Acceptance metrics

Primary:

- non-push hit rate
- calibration/trust sanity of selected candidates

Product:

- weekly coverage
- no-play reason mix

Reported but not optimized:

- ROI
- average odds
- EV

### Evidence already established

The preregistered HALF_SHRINK diagnostic preserved exact development coverage and moved HHR hit rate in the favorable direction while retaining strong overlap with pure model rank 1. It did not collapse into a Pinnacle selector. This architecture freezes the **model-led corroboration mechanism**, not a claim of production validation.

## 5. Protocol B — Balanced

### Product question

> Which supported wager gives a strong chance to win at a genuinely reasonable price?

Balanced is the primary casual-facing feature.

### Objective

**Probability first, price constrained.**

Balanced is not Value Lite.

### Candidate universe

V1 headline-eligible markets:

- moneyline
- spread with Spread Confidence V3 support

Totals remain excluded until validated for headline selection.

Candidate must have:

- supported football/model-confidence evidence
- sufficient historical/model-confidence support
- exact actionable DK/FD offer
- acceptable reliability/support
- actual sportsbook price inside the frozen Balanced price band

Balanced must **not** require:

- strict positive EV
- `VALUE` status
- positive model-price gap
- positive evaluator EV

A small negative exact-offer EV does not automatically eliminate a high-probability Balanced play if it remains inside the frozen price/product constraints. Conversely, an attractive EV number cannot elevate a low-confidence candidate above a stronger probability candidate.

### ML trust requirement

Balanced must remain football-model first while correcting the observed maximum-confidence / constituent-disagreement problem.

Architecture requirement:

```text
balanced_trust = model-confidence-led trust with an explicit QB-Elo/XGBoost agreement correction
```

The exact final agreement transform is the **one remaining Balanced freeze item**. It must be preregistered before the final integrated 2020-24 run and may not be selected by searching arbitrary coefficients after outcomes are seen.

Known constraints from completed diagnostics:

- raw maximum model confidence alone is vulnerable to rank-1 anti-selection;
- QB-Elo/XGBoost disagreement contains useful trust information;
- a universal fixed disagreement penalty was not stable enough to promote directly;
- model confidence itself remains broadly calibrated and must not be replaced by Pinnacle/evaluator confidence.

For spread, Balanced uses Spread Confidence V3 rather than the superseded high-tail spread conversion.

### Ranking order

Final implementation must preserve this semantic order:

1. Balanced model trust / trustworthy probability
2. model confidence
3. reliability/support
4. actual price quality within the allowed price band
5. deterministic exact-offer/book/candidate tie-break

EV and Value/Playable status are not primary ranking fields.

### Acceptance metrics

Primary:

- non-push hit rate
- probability/calibration sanity
- actual price distribution

Product-critical:

- weekly coverage
- no-play reason mix

Secondary reporting:

- ROI
- EV

Balanced coverage is a product requirement to monitor, not a threshold-tuning objective.

## 6. Protocol C — Value

### Product question

> Which exact current offer has a genuine historically supported positive expected-value advantage?

### Objective

**Strict +EV only.**

Value may legitimately return no play.

### Candidate requirements

A Value candidate must satisfy all of the following:

- historically supported football-model candidate/family
- supported model-confidence evidence where applicable
- supported Task05F exact-offer evaluation
- exact current DK/FD offer
- strict evaluated EV > 0
- `VALUE` status; `PLAYABLE` can never substitute for Value
- reliability/support/OOD guardrails
- frozen Value price sanity band

### Candidate-family allowlist

Value is allowed to be narrower than HHR/Balanced.

Current evidence supports:

- Expected-Margin spread value regions as a credible V1 family
- selected ML candidate families only if the final ML family audit supports retaining them

Current evidence does **not** authorize totals as a headline Value family. Totals stay out until upstream betting edge is demonstrated.

The exact ML Value allowlist is the **one remaining Value freeze item** because later-period ML value decayed materially while spread value was more stable.

### Ranking

Do **not** rank the unrestricted board by maximum estimated EV.

The validated architecture is:

```text
football-model supported family
    -> exact Task05F strict +EV filter
    -> model/evaluator consensus support
    -> deterministic economic ranking among surviving legitimate candidates
```

A defensible final ordering is model/evaluator consensus edge first, then model confidence/reliability, with exact EV used as an economic discriminator among supported survivors rather than as an unrestricted max-EV optimizer.

### Acceptance metrics

Primary:

- strict +EV validity
- EV/edge calibration
- historical support

Secondary:

- ROI
- hit rate

Product:

- weeks with legitimate Value

No minimum weekly coverage is required.

## 7. Cross-lane prohibitions

These are testable invariants.

### HHR must not

- require positive EV
- rank max EV
- require `VALUE`/`PLAYABLE`
- use Pinnacle as the primary probability model
- use Task05F market-dominated probability as a substitute for football model confidence

### Balanced must not

- rank `VALUE` before probability
- rank EV before probability
- require strict positive EV
- use max-EV selection
- become a Pinnacle selector

### Value must not

- accept `PLAYABLE` as Value
- select negative/zero EV
- use unrestricted max-EV over unsupported families
- loosen thresholds to create weekly action

## 8. Coverage contract

For an 18-week season:

```text
HHR      = 18 possible weekly slots
Balanced = 18 possible weekly slots
Value    = 18 possible weekly slots
Total    = 54 possible lane-slots
```

Twice-daily refreshes update the current slot; they do not increase this count.

Desired behavior:

- HHR: available most weeks
- Balanced: available most weeks and treated as the main casual product
- Value: only when genuine strict +EV exists

Coverage is an acceptance diagnostic. It must not be optimized by weakening reliability/support rules after outcomes are seen.

Every HHR/Balanced no-play must carry a deterministic reason code, such as:

- `NO_MODEL_CONFIDENCE_SUPPORT`
- `NO_SUPPORTED_MARKET`
- `NO_EXACT_ACTIONABLE_OFFER`
- `RELIABILITY_UNSUPPORTED`
- `PRICE_OUTSIDE_PRODUCT_BAND`
- `NO_CANDIDATE_AFTER_SHOPPING`

Value adds:

- `NO_STRICT_POSITIVE_EV`
- `NO_VALIDATED_VALUE_FAMILY`

## 9. Required selector-separation tests

The final implementation must include tests proving protocol independence.

### HHR

- changing EV while holding football confidence/support/price fixed cannot change HHR ranking
- changing `VALUE` to `PLAYABLE`/`LEAN` cannot change HHR ranking unless support itself changes
- extreme model-over-Pinnacle ML confidence is only partially tempered, not replaced by Pinnacle
- Spread V3 is the only spread confidence conversion accepted

### Balanced

- changing EV/status while holding model trust and allowed price fixed cannot promote a lower-trust candidate
- a lower-probability high-EV candidate cannot outrank a higher-trust candidate solely because of EV
- price outside the Balanced band fails eligibility
- QB-Elo/XGBoost agreement logic cannot mutate the underlying calibrated model probability

### Value

- EV <= 0 always fails
- `PLAYABLE` always fails
- unsupported family always fails even with large estimated EV
- unrestricted maximum EV cannot bypass family/support ordering

### Global

- same candidate table -> deterministic same three selections
- selector outputs may differ from one another for principled reasons
- 2025 data entering development/audit execution hard-fails

## 10. Final bounded digging before implementation freeze

Only the following selector questions remain open. They are bounded and may not expand into another broad search.

### A. HHR/Balanced no-play coverage audit

For every 2020-24 block where HHR or Balanced is absent, attribute the exact gate responsible.

Goal: determine whether current missing coverage comes from real lack of supported candidates or from accidental legacy economic/status gates.

Do **not** tune thresholds to hit a desired coverage number.

### B. Balanced agreement correction

Preregister one final model-led agreement mechanism and compare it with raw model-confidence ranking while preserving the same eligibility universe and coverage.

Goal: prevent implausible max-confidence selections without replacing football confidence with market confidence.

### C. Value ML-family audit

Determine whether any ML family has enough cross-period support to remain V1 Value-eligible. Spread value remains separately evaluated. Totals remain excluded unless new evidence specifically authorizes them.

Goal: freeze a small explicit Value family allowlist before 2025.

### D. Integrated 2020-24 selector simulation

After A-C are frozen, run one integrated simulation using the exact final protocols and report:

- HHR/Balanced/Value weekly coverage
- hit rate by lane
- exact price distribution by lane
- market mix
- model-rank / Pinnacle-rank overlap
- no-play reason counts
- Value strict-EV/family provenance
- lane overlap
- refresh-stability mechanics where historical snapshots support it

No further selector tuning is allowed after this integrated development review except genuine implementation defects.

## 11. 2025 firewall

2025 remains sealed until all of the following are frozen and hashed:

- model-confidence conversions
- HHR protocol and price band
- Balanced agreement correction and price band
- Value family allowlist and strict +EV protocol
- selector code/config
- recommended-unit policy
- five risk-profile mappings
- tests
- production output contract

2025 is then opened once for untouched acceptance. No 2025-driven selector redesign.
