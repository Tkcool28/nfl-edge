# Task05G Final Policy Reconciliation V1 — Preregistration

## Purpose

Reconcile the already-frozen Task05G downstream policy with the final canonical three-lane selector freeze before changing any unit, risk-profile, or Play Through rule.

This is not a selector experiment. The selector contract is frozen at:

`f1611bd42475bf05c49188e07dfb494e5e1ce86e`

and must remain byte-identical in this branch.

## In-scope downstream Task05G contract

The original Task05G policy and the updated Market Evaluation Layer V1.2 plan place the following in scope before opening 2025:

1. deterministic `recommended_units`;
2. five ordered risk profiles;
3. bankroll-to-dollar conversion;
4. per-wager and slate caps, minimum stake, rounding, and exact-offer overlap deduplication;
5. Play Through / `PLAYABLE` exact-offer behavior;
6. stored-offer and manual-offer parity;
7. chronological 2020-2024 product/card and bankroll simulation;
8. backend recommendation/user-facing output contract required for the sealed-2025 production replay.

Full frontend implementation, static-site design, live deployment, and production hosting are out of scope for this reconciliation milestone.

## Frozen downstream candidate policy under test

No unit/risk-profile/Play Through threshold is changed before this replay.

### Unit ladder

`0.0, 0.5, 0.75, 1.0, 1.25, 1.5`

Existing `recommended_units` policy:

- unsupported -> 0u;
- reliability outside HIGH/MEDIUM -> 0u;
- PASS / LEAN / UNSUPPORTED -> 0u;
- PLAYABLE -> 0.75u when HIGH and actionable_probability >= .55, otherwise 0.5u;
- VALUE:
  - HIGH, EV >= .06, actionable_probability >= .55, uncertainty <= .025 -> 1.5u;
  - HIGH, EV >= .04, actionable_probability >= .52 -> 1.25u;
  - EV >= .025, actionable_probability >= .50 -> 1.0u;
  - otherwise -> .75u.

### Five risk profiles

- Cautious: 1u = 0.50% bankroll
- Steady: 1u = 0.75%
- Balanced: 1u = 1.00%
- Bold: 1u = 1.25%
- High Gear: 1u = 1.50%

### Dollar-risk rules

- per-wager cap = 2.5% bankroll;
- slate cap = 10% bankroll;
- minimum displayed stake = $0.50;
- round down to nearest $0.50;
- exact duplicate offer across headline roles counts once toward exposure.

### Play Through

- strict `VALUE` remains strict evaluated EV > 0;
- `PLAYABLE` is separate and never relabeled Value;
- concession corridor = exactly 1.5 percentage points of break-even probability;
- unsupported cannot be promoted;
- manual and stored exact offers use the identical evaluator/Play Through path.

## Primary reconciliation questions

Report these without threshold search or outcome-based tuning:

1. For each final lane, what share of selected headlines receives 0u under the existing downstream policy?
2. What is the selected headline status mix (`VALUE`, `PLAYABLE`, `LEAN`, `PASS`, `UNSUPPORTED`)?
3. What is the reliability mix and how often does LOW/UNSUPPORTED create a selected-but-0u headline?
4. For nonzero recommendations, what is the unit distribution by lane?
5. How often do lanes overlap on the exact same offer, and does exposure deduplication behave deterministically?
6. Under each frozen risk profile, what would a $100 starting-bankroll chronological 2020-2024 simulation look like when every unique nonzero weekly headline recommendation is followed subject to the frozen wager/slate caps?
7. Do 2023 safety improvements remain contained under unit staking rather than being erased by staking behavior?
8. Do stored/manual exact-offer Play Through paths remain identical?

## Decision rule

Do **not** modify unit sizes or risk-profile percentages because one historical bankroll simulation has higher ROI.

If the existing policy is mechanically coherent with the final selectors, freeze it unchanged.

If a product-contract conflict is exposed (for example, many HHR/Balanced featured cards are intentionally selected but always carry 0u), document the conflict and make a minimal semantic product decision. Any such decision must be justified by lane meaning and risk honesty, not historical profit optimization, and must be frozen before a second replay.

## Firewall

2025 remains sealed. The reconciliation workflow must hard-fail if 2025 enters development data or outcome/replay artifacts.
