# Task05G — Selector + Unit Policy Validation Review

## Verdict

**TASK05G_PARTIAL**

The Task05G downstream implementation is deterministic, tested, exact-offer compatible, security-clean, and preserves the Task05F/football-model/2025 firewalls. The frozen Hit Rate selector has acceptable development evidence. The frozen Balanced and Value headline selectors do **not** have acceptable 2020–2024 development evidence and therefore the complete selector policy is not ready for promotion.

No Task05F evaluator or football model was changed. No 2025 outcome was loaded. No post-hoc selector family was selected after observing ROI.

Validated implementation head: `028e1c3eced2e0e58dc40e63bb4e367498de0cfd`.

Validation workflow: run `32671579900`, job `97273120591`, conclusion `success`.

Validation artifact: `9501536928`, digest `sha256:fce50cb4fd0ee400e663884f5ffa8beb00442d6c93bdd564b9bf616a76db2b4b`.

The artifact contains the reviewed Task05G reports plus the 2020–2024 upstream `historical_evaluator_board.parquet`, `candidate_table.parquet`, and Task05F scorecard. Evidence-only commits under `reports/task05g/` after the validated implementation head do not alter policy code.

## Required handoff

### 1. Final verdict

`TASK05G_PARTIAL`.

Mechanics and contracts are implemented and validated. Hit Rate is supportable from development evidence; Balanced and Value are not supportable as frozen headline selectors.

### 2. Starting main / HEAD

`main` / `origin/main`: `4984ea1ee38377f7f5016d2081be8f7c43bda4cd`, the Task05F merge commit.

The feature branch was created from that exact commit. GitHub comparison at the validated implementation head was ahead 12 / behind 0.

### 3. Working branch / HEAD

Branch: `feat/task05g-selectors-units-v1`.

Validated implementation head: `028e1c3eced2e0e58dc40e63bb4e367498de0cfd`.

### 4. Exact Hit Rate eligibility rules

- exact shopped DraftKings/FanDuel offer
- evaluator supported
- reliability `HIGH` or `MEDIUM`
- price status `VALUE` or `PLAYABLE`
- actionable probability >= `0.55`
- American odds from `-300` through `+200`

### 5. Exact Hit Rate ranking

1. actionable probability descending
2. `HIGH` reliability before `MEDIUM`
3. `VALUE` before `PLAYABLE`
4. expected value descending
5. better American price
6. candidate ID ascending

### 6. Exact Balanced eligibility rules

- exact shopped DraftKings/FanDuel offer
- evaluator supported
- reliability `HIGH` or `MEDIUM`
- price status `VALUE` or `PLAYABLE`
- actionable probability >= `0.50`
- expected value >= `-0.03`
- American odds from `-220` through `+200`

### 7. Exact Balanced ranking

1. `VALUE` before `PLAYABLE`
2. `HIGH` reliability before `MEDIUM`
3. expected value descending
4. actionable probability descending
5. evaluated edge probability descending
6. candidate ID ascending

Validation note: this hierarchy selected `VALUE` in 64/67 plays and matched the exact Value headline in 34 blocks. In development it behaved too much like a second Value selector and failed promotion evidence.

### 8. Exact Value eligibility rules

- exact shopped DraftKings/FanDuel offer
- evaluator supported
- reliability `HIGH` or `MEDIUM`
- strict Task05F `VALUE`
- actionable probability >= `0.35`
- American odds from `-180` through `+250`
- expected value >= `0.02`
- `support_n >= 256`
- `support_distance <= 0.05`
- `uncertainty <= 0.045`

### 9. Exact Value ranking

1. expected value descending
2. evaluated edge probability descending
3. `HIGH` reliability before `MEDIUM`
4. actionable probability descending
5. candidate ID ascending

### 10. Longshot guardrail

Headline Value requires probability >= 35%, odds no longer than +250, EV >= 2%, HIGH/MEDIUM reliability, support >= 256, support distance <= 0.05, and uncertainty <= 0.045.

Observed headline guardrail violations: **0**.

Three Value threshold families were preregistered before broad retrospective evaluation and then evaluated only as sensitivity diagnostics:

| Family | Min probability | Max odds | Min EV | Plays | ROI |
|---|---:|---:|---:|---:|---:|
| Conservative | 40% | +200 | 3.0% | 51 | -17.63% |
| Frozen primary | 35% | +250 | 2.0% | 61 | -18.45% |
| Permissive | 30% | +300 | 1.5% | 64 | -28.50% |

All three were negative in every active season for which the family selected plays. `family_selection_performed=false`; no family was substituted after seeing ROI.

### 11. Selector overlap behavior

Overlap is allowed. Picks are never forced apart for UI variety.

Observed primary-policy overlap:

- Balanced and Value same exact offer: 34 blocks
- all three same exact offer: 6 blocks

The same exact offer is counted once for slate exposure.

### 12. No-play behavior

Valid no-play outputs are:

- `NO_HIT_RATE_PLAY`
- `NO_BALANCED_PLAY`
- `NO_VALUE_PLAY`

No selector is forced to produce a wager.

### 13. Play Through classification contract

Frozen Task05F statuses are preserved:

- `VALUE`: strict EV > 0
- `PLAYABLE`: supported, non-value offer inside the frozen concession corridor
- `LEAN`: supported/model preference but outside playable range
- `PASS`: supported/evaluated but not attractive/complete enough for active presentation
- `UNSUPPORTED`: fail closed and never converted to PASS

### 14. Exact 1.5pp concession behavior

`0.015` is the maximum break-even concession. The Task05F confidence multiplier may reduce the actual concession according to reliability/uncertainty. Task05G does not retune it.

Alternate offers must be evaluated at their exact market/side/line/price with `evaluate_offer(...)`; a derived synthetic threshold cannot approve an offer.

### 15. Recommended-unit ladder

`0u, 0.5u, 0.75u, 1u, 1.25u, 1.5u`.

No continuous/Kelly precision is used.

### 16. Exact unit assignment rules

- `UNSUPPORTED`, `PASS`, `LEAN`, unsupported evaluator, or reliability outside HIGH/MEDIUM: `0u`
- `PLAYABLE`: `0.5u`
- `PLAYABLE` + HIGH reliability + probability >= 0.55: `0.75u` maximum
- `VALUE`: `0.75u` floor
- `VALUE` + EV >= 0.025 + probability >= 0.50: `1u`
- HIGH `VALUE` + EV >= 0.04 + probability >= 0.52: `1.25u`
- HIGH `VALUE` + EV >= 0.06 + probability >= 0.55 + uncertainty <= 0.025: `1.5u`

Observed unique headline-wager unit mix: 13 at 0.5u, 69 at 0.75u, 63 at 1u, 0 at 1.25u, 0 at 1.5u. This is consistent with the fact that almost all selected evidence was MEDIUM reliability.

### 17. Five risk-profile names

1. Cautious
2. Steady
3. Balanced
4. Bold
5. High Gear

### 18. Bankroll percentage per unit

- Cautious: `0.50%`
- Steady: `0.75%`
- Balanced: `1.00%`
- Bold: `1.25%`
- High Gear: `1.50%`

Profiles change dollars only; they do not change selector identity, evaluator output, EV/status, or recommended units.

### 19. Stake rounding rule

`bankroll × profile_unit_pct × recommended_units`, bounded by caps, then floored to the nearest `$0.50`.

Computed/capped stakes below `$0.50` become `$0`.

### 20. Wager cap

Per-wager cap: `2.5%` of current bankroll.

### 21. Slate cap

Slate-level cap: `10%` of current bankroll. Duplicate headline roles on the same exact offer count once.

### 22. 2020–2024 selector coverage

There were 109 chronological season-week blocks.

Hit Rate weeks with play: 59; no play: 50.

Balanced weeks with play: 67; no play: 42.

Value weeks with play: 61; no play: 48.

Value season coverage:

- 2020: 0 — NOT READY FOR HEADLINE PROMINENCE
- 2021: 8 — ACCEPTABLE
- 2022: 17 — STRONG
- 2023: 17 — STRONG
- 2024: 19 — STRONG

Coverage bands are interpretation only and were not used as targets.

### 23. Hit Rate historical diagnostics

- plays: 59
- non-push hit rate: `69.49%`
- ROI/unit risked: `+6.30%`
- average actionable probability: `67.53%`
- average odds: `-209.46`
- average EV: `+2.15%`
- reliability: 59 MEDIUM, 0 HIGH/LOW/UNSUPPORTED

Season ROI: 2021 +29.52%, 2022 +7.16%, 2023 -15.58%, 2024 +17.78%. Positive in 3 of 4 active seasons.

### 24. Balanced historical diagnostics

- plays: 67
- non-push hit rate: `45.45%`
- ROI/unit risked: `-15.12%`
- average actionable probability: `55.45%`
- average odds: `-92.66`
- average EV: `+4.68%`
- reliability: 66 MEDIUM, 1 HIGH

Season ROI: 2021 -39.35%, 2022 +22.84%, 2023 -32.32%, 2024 -23.13%. Negative in 3 of 4 active seasons.

**Promotion verdict: failed development evidence.**

### 25. Value historical diagnostics

- plays: 61
- non-push hit rate: `38.33%`
- ROI/unit risked: `-18.45%`
- average actionable probability: `49.84%`
- average odds: `+11.31`
- average evaluator EV: `+6.71%`
- reliability: 61 MEDIUM

Season ROI: 2021 -18.51%, 2022 -9.24%, 2023 -26.25%, 2024 -19.67%.

**Negative in every active season. Promotion verdict: failed development evidence.**

### 26. Market mix

Hit Rate: 54 ML / 5 spread / 0 total.

Balanced: 26 ML / 28 spread / 13 total.

Value: 32 ML / 17 spread / 12 total.

No market was forced into a selector.

### 27. Season stability

Hit Rate was positive in 3 of 4 active seasons.

Balanced was negative in 3 of 4 active seasons.

Value was negative in all 4 active seasons.

The Value failure was also stable across all three preregistered threshold families, so it cannot be attributed only to the frozen-primary longshot fence.

### 28. Risk-profile bankroll diagnostics

All simulations start with `$1,000`, use the identical 145 unique headline wagers, and de-duplicate overlapping roles.

- Cautious ending bankroll: `$939.26`; total risked `$563.00`; average wager `$3.88`
- Steady: `$906.56`; total risked `$863.50`; average wager `$5.96`
- Balanced: `$878.52`; total risked `$1,142.50`; average wager `$7.88`
- Bold: `$847.17`; total risked `$1,431.50`; average wager `$9.87`
- High Gear: `$816.37`; total risked `$1,708.00`; average wager `$11.78`

The monotonically worse dollar outcomes at higher risk reflect the same losing selector stream, not a change in selector identity or units.

### 29. Maximum drawdowns

- Cautious: `7.55%`
- Steady: `11.45%`
- Balanced: `14.90%`
- Bold: `18.62%`
- High Gear: `22.06%`

Worst losing streak: 5 wagers for every profile.

Peak observed slate exposures: 1.35%, 2.04%, 2.73%, 3.42%, and 4.07%, respectively, all below the frozen 10% cap.

### 30. Longshot behavior

Primary Value longshot-guardrail violations: `0`.

The poor Value result was not rescued by the preregistered conservative fence: conservative Value still returned `-17.63%` ROI over 51 plays. No post-hoc odds band, market exception, or threshold slice was adopted.

### 31. Manual-offer compatibility proof

`evaluate_policy_offer(...)` passes the exact supplied normalized offer to frozen Task05F `evaluate_offer(...)`, then applies Play Through and unit policy.

Focused test `test_manual_and_full_board_policy_are_source_agnostic` passed. Task05F regeneration also completed 7,594 stored/manual parity checks.

### 32. Full-board compatibility proof

The same exact-offer policy adapter is source agnostic. No selector-only stake path exists. Unit recommendation works for any supported exact evaluated offer, including future clicked DK/FD boxes and manual offers.

Best-book shopping has focused tests for ML, spread, Over, and Under semantics.

### 33. 2025 firewall proof

CI verified both regenerated Task05F `historical_evaluator_board.parquet` and `candidate_table.parquet` contain exactly seasons `{2020,2021,2022,2023,2024}` before selector evaluation.

The Task05G sensitivity script repeats the same season firewall. Focused candidate-contract test rejects season 2025.

2025 outcomes were not opened for Task05G.

### 34. Proof evaluators were unchanged

CI compared against base `4984ea1ee38377f7f5016d2081be8f7c43bda4cd` and required an empty diff under `src/nfl_edge/value/`.

Reviewed `frozen_scope_diff.txt` is empty.

### 35. Proof football models were unchanged

The same CI scope gate required an empty diff under `src/nfl_edge/models/`, `src/nfl_edge/backtest/`, `data/modeling/`, `data/frozen/`, and frozen Task05D/Task05E evidence.

Reviewed frozen-scope diff is empty.

### 36. Tests

Focused Task05F + Task05G suite: **39 passed**.

The workflow also compiled policy/sensitivity code, regenerated Task05F, ran Task05G twice, ran preregistered sensitivity twice, byte-compared deterministic outputs, checked policy invariants, and uploaded evidence. All steps passed in workflow run `32671579900`.

### 37. Security proof

Security scan passed with no Task05G dependency on or serialization of `os.environ`, `os.getenv`, API keys, access tokens, secret keys, `.env`, PEM/key files, credentials files, or secret-bearing paths.

No credentials or environment variables appear in the reviewed Task05G artifacts.

### 38. Git status

GitHub compare at validated implementation head: feature branch ahead 12 / behind 0 from the exact Task05F merge base.

All implementation changes are committed on `feat/task05g-selectors-units-v1`. No merge was performed. Evidence-only report commits may follow the validated implementation head but do not alter frozen code/model scopes.

The production `/root/nfl-edge` working tree was not modified by this GitHub-only implementation session; its local untracked runtime/audit inventory was not touched.

### 39. Commits / PR

Validated implementation contains 12 commits after the Task05F merge base. Major final validation commits include:

- `a3e0b6cb9ef9622b8117d4506012f0cba2663d9d` — retain upstream board in validation evidence
- `74827abd8f85df9d59342fd5a1cced54360f23e3` — preregistered selector sensitivity diagnostic
- `028e1c3eced2e0e58dc40e63bb4e367498de0cfd` — deterministic sensitivity validation workflow

PR: **#25**, open, draft, unmerged.

Temporary CI-only PRs #26 and #27 were closed without merge.

### 40. Exact recommended next milestone

**Do not open 2025 and do not begin frontend work.**

Next milestone should be a narrowly scoped **Task05G selector-policy remediation/preregistration milestone** that starts from the evidence in this report and defines a new conceptually justified Balanced/Value policy design *before any further broad retrospective scoring*.

The remediation must not:

- select the conservative Value family merely because it lost less;
- add spread-only or other market-specific rescue rules based on these results;
- search many odds/EV/probability slices;
- retune ML V4 / Spread V3 / Total V3;
- retune football models;
- inspect 2025.

The structural issue to address is that the current Balanced ranking is effectively Value-like, while global evaluator EV is not sufficient by itself to support a market-agnostic headline Value ranking. Any replacement should be preregistered, simple, interpretable, and evaluated chronologically with 2025 still sealed.
