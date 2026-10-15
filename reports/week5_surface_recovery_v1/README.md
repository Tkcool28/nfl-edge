# Week 5 surface recovery: blocked at evidence verification

**BLOCKED_NFL_EDGE_WEEK6_RECOVERY**

Start main: `dfcb5b9bde05dfbd942179b7d2ca3ea7ce2ea836`.
Start PR #142: `551cc370448eb9c629afd959b11a296e00ba4c51`, open/draft/unmerged.
The two supplied evidence files were read before this report was prepared. All ZIP manifest hashes match. This review makes no runtime, model, evaluator, roof, settlement or operational changes.

## Exact stop condition

The first missing-surface game is `2026_05_PHI_JAX`, October 11, 2026, at Tottenham Hotspur Stadium. Raw `JAX00` is retained as an upstream identifier; it is not evidence of Jacksonville venue characteristics.

The official stadium confirms a dedicated artificial NFL field. The manufacturer's September 2024 release describes Matrix Helix for that year's NFL London installation. A current search-indexed statistical venue listing instead labels Tottenham `a_turf` through 2026; direct page retrieval returned 403. Neither a 2024 installation nor a conflicting index entry is accepted here as proof of the exact October 2026 token. The generic `artificial` suggestion in the supplied audit is absent from the observed frozen training vocabulary. The task explicitly requires stopping before applying unresolved values, so **zero overrides are applied**.

Smallest next action: obtain the NFL/Hellas 2026 London field installation specification or authoritative game-specific surface record, resolving this game to an existing accepted token. Then finish the remaining per-game verification and implement only the bounded Week 5 registry. No architecture or methodology change is needed to continue the evidence work.

## Pipeline finding

Surface is both metadata and an accepted Ridge Totals R4 predictor:

- `schedule_materializer_2026.py`: requires a nonempty value and lowercases it.
- `schedule_2026.py`: no surface-category enum; rejects missing surface and exact game-field drift.
- `evidence_2026.py`: builds historical weekly schedules before downloading settled statistics.
- `features_2026.py`: copies schedule surface into current-game context.
- `totals_features.py`: passes surface into the frozen exact-90 feature emitter.
- `features/totals_v1/context_features.py`: lowercases surface without grouping brands.
- `backtest/totals_bake_off.py`: frozen Ridge one-hot encoding uses `handle_unknown="ignore"`. This is an inference fallback, not a justification to introduce a different surface category.
- `roof.py` and `venue_structure_2026.py`: existing independent roof logic remains untouched. Existing QB overrides require explicit keyed records/provenance; no generic surface override mechanism exists.

Observed 2018–2024 `surface_category` vocabulary in the accepted modeling table: empty string, `a_turf`, `astroturf`, `fieldturf`, `grass`, `grass `, `matrixturf`, `sportturf`. This is an observed vocabulary, not a newly imposed global schema or an approval of any candidate below.

## Inventory of the 14 missing source rows

All are season 2026, REG Week 5. Every candidate remains **unapplied and unapproved**; the investigation stopped at the first unresolved exact-token gate. The supplied audit's categorical labels must not be mistaken for completed independent game-specific verification.

| Source game ID | Venue | Raw ID | Audit class | Existing-token candidate, not approved |
|---|---|---|---|---|
| 2026_05_PHI_JAX | Tottenham Hotspur Stadium | JAX00 | artificial | matrixturf / a_turf unresolved |
| 2026_05_CHI_GB | Lambeau Field | GNB00 | grass | grass |
| 2026_05_CIN_MIA | Hard Rock Stadium | MIA00 | grass | grass |
| 2026_05_LV_NE | Gillette Stadium | BOS00 | artificial | fieldturf |
| 2026_05_MIN_NO | Caesars Superdome | NOR00 | artificial | sportturf |
| 2026_05_CLE_NYJ | MetLife Stadium | NYC01 | artificial | fieldturf |
| 2026_05_IND_PIT | Acrisure Stadium | PIT00 | grass | grass |
| 2026_05_HOU_TEN | Nissan Stadium | NAS00 | artificial | matrixturf |
| 2026_05_NYG_WAS | Northwest Stadium | WAS00 | grass | grass |
| 2026_05_DEN_LAC | SoFi Stadium | LAX01 | artificial | matrixturf |
| 2026_05_DET_ARI | State Farm Stadium | PHO00 | grass | grass |
| 2026_05_SF_SEA | Lumen Field | SEA00 | artificial | fieldturf |
| 2026_05_BAL_ATL | Mercedes-Benz Stadium | ATL97 | artificial | fieldturf |
| 2026_05_BUF_LA | SoFi Stadium | LAX01 | artificial | matrixturf |

Canonical last-game ID would be `2026_05_BUF_LAR`; raw identity must also match any eventual recovery record. Raw stadium IDs are never rewritten.

Gillette: contemporary August 2026 reporting supports FieldTurf reinstatement following temporary World Cup grass; the old 2024 installation alone would be insufficient. Nissan: official Titans evidence establishes the 2023 Matrix Helix conversion, with the replacement stadium planned for 2027. Historical grass majority cannot override that fact. Caesars and Northwest aliases/candidate labels are recorded in JSON, but are not promoted into approved evidence. No assumptions about surface subtypes, international venue identity or roof status are applied.

## Retained sources and validation

`evidence_review.json` records source URLs, source descriptions, retrieval date, quality, exact source rows, both raw CSV digests and the precise blocker. Original raw CSV SHA-256:

`8b455c694bd589d0c16644438cb7fa8b9f5bde88dcb8fa6721bea03e13c90c02`

A fresh source fetch has SHA-256 `5c6a29a526bb23dc81ab00cbb2cfabcaac80d95474f6a84a7e701db48cddd8a2`; its 14 missing Week 5 surfaces remain missing. It also contains `2026_05_TB_DAL` with an existing surface. Therefore the 14-game recovery inventory is not a claim that the entire current Week 5 slate has only 14 games.

Regression command:

```
python -m pytest -q tests/live/test_schedule_materializer_2026.py tests/live/test_schedule_2026.py tests/live/test_evidence_2026.py
```

Result: **28 passed**. This includes future-week isolation, active-week fail-closed and Tuesday Denver rollover. Recovery-specific override tests are not claimed: no override implementation is present.

No authentic Week 5 reconstruction, football-state advancement or canonical full pre-provider run was attempted after the evidence stop gate. The existing successful Week 6 schedule result from PR #142 remains a schedule-only result. It cannot certify the full recovery.

Paid provider requests: **0**. Odds API called: **false**. Market data consumed by validation: **false**. No production/VPS access, restart, timer changes, product publication, model training, recalibration, merge or deployment.
