# Minimal surface recovery V1 — exact accepted-input finding

Verdict: **BLOCKED_NFL_EDGE_WEEK6_RECOVERY**.

Remote starting main: dfcb5b9bde05dfbd942179b7d2ca3ea7ce2ea836.
PR #142 starting head: 551cc370448eb9c629afd959b11a296e00ba4c51.
PR #143 starting head: 9d1e30598712f600637b1f04791103c2ecdf2d7b.
Both PRs remain open and unmerged.

## What the model actually receives

The schedule materializer lowercases surface strings; historical and live feature bridges retain them. The frozen Totals context extractor lowercases without merging turf classes. Surface category is one of the exact 90 R4 predictors. The final accepted pipeline independently one-hot encodes roof_category and surface_category, with unknown categories ignored. No manufacturer-name field is passed to a model.

The supplied script constructs only the **existing accepted preprocessing** from the 1,942 development predictor rows (2018–2024), excluding target/outcome columns. It intercepts `Ridge.fit` and network calls with hard failures. It does not fit, recalibrate, select or alter a predictive estimator. Zero predictive fitting calls and zero network calls occurred in the probe.

Actual surface vectors, displaying only the four columns below:

| Input | grass | a_turf | fieldturf | matrixturf |
|---|---:|---:|---:|---:|
| grass | 1 | 0 | 0 | 0 |
| a_turf | 0 | 1 | 0 | 0 |
| fieldturf | 0 | 0 | 1 | 0 |
| matrixturf | 0 | 0 | 0 | 1 |

`astroturf` and `sportturf` also activate separate existing columns. Generic `artificial` activates none of the eight observed surface columns. Switching any two known distinct labels gives surface-vector L1 distance 2. This is a representation difference, **not a measured two-point prediction change**.

For fixed fitted coefficients and every other input held constant, the R4 point difference for labels A and B is exactly `beta_B - beta_A`. Equal coefficients would yield no point difference despite different vectors. The repository contains no serialized fitted R4 model or surface coefficient artifact found by inspection; the canonical live adapter creates/fits accepted R4 from prior history during scoring. This diagnostic does not run a new predictive fit under the no-retraining restriction and does not claim a numerical point sensitivity, nonzero fitted effect or practical importance.

Therefore: the accepted representation does distinguish turf labels; manufacturer causality or practical importance has not been demonstrated. The earlier investigation's implication that separate indicators by themselves prove material manufacturer effects was too strong. A grass/artificial collapse would still change the frozen representation and is not an authorized ingestion repair.

## Tottenham and the smallest unresolved requirement

Actual venue: Tottenham Hotspur Stadium. Official evidence establishes its artificial NFL field. `JAX00` is not used to infer physical venue or surface. No grass assumption is permitted.

A justified existing source-category token is required. The reviewed evidence has an indexed `a_turf` classification but historical manufacturer Matrix Helix evidence; it does not independently resolve the actual October 2026 canonical input. No token is silently substituted. No additional manufacturer research was performed during this minimal-input diagnostic.

A check of the upstream's own archived 2026 Week 5 rows at commit `274208b589d7f4e68e32b431384b74965d2395a4` (2026-10-10T11:35:13Z) found **grass** for both Tottenham and Nissan. These are contradicted by the verified venue facts. Blindly restoring an earlier source snapshot is therefore also unsafe. Immutable source URL:

https://raw.githubusercontent.com/nflverse/nfldata/274208b589d7f4e68e32b431384b74965d2395a4/data/games.csv

Smallest next step: obtain an authoritative game-specific source-category record for `2026_05_PHI_JAX`, or a reviewed documented mapping resolving the category conflict while preserving the accepted encoding. Manufacturer identity beyond what establishes that input is unnecessary. This report does not request a model redesign or a new stadium database.

## All 14 corrections and recovery status

Applied corrections: **0 of 14**. The complete 14-game candidate inventory remains in evidence_review.json, with all approvals false. Tottenham is established as artificial but has no approved exact token. The other 13 entries are not presented as independently completed corrections. No historical or current-week schedule values are altered.

Week 5 settled-evidence reconstruction: **not completed**.
Model-state advancement into Week 6: **not executed**.
Full canonical Week 6 pre-provider verdict: **not obtained**.
The prior real Week 6 schedule result remains 14 games at PR #142, not a complete recovery proof.

Paid provider requests: **0**. Odds API used: **false**. Market data consumed for this audit: **false**. Only predictor columns were loaded; no targets were selected. No VPS access, deployment, publication, merge, runtime code or methodology change occurred.

## Reproduction and tests

```
PYTHONPATH=src python scripts/audit_surface_encoding_v1.py
python -m pytest -q tests/live/test_schedule_materializer_2026.py tests/live/test_schedule_2026.py tests/live/test_evidence_2026.py tests/features/test_totals_v1_context.py
```

The script output is retained in encoding-result.json. Existing schedule, settled-evidence and frozen-context regressions: **36 passed**. These tests do not establish authentic settled replay or full pre-provider readiness, and recovery-override tests are not claimed because no recovery overrides were applied.
