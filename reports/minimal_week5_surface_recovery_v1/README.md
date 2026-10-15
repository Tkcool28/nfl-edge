# Minimal Week 5 surface recovery

The user authorized the one-game Tottenham exception after reviewing the actual accepted surface encoding. This implementation supersedes the earlier investigation's stop on that unresolved subtype.

Starting main: `dfcb5b9bde05dfbd942179b7d2ca3ea7ce2ea836`.
Corrected schedule-builder base: PR #142, `551cc370448eb9c629afd959b11a296e00ba4c51`.
Investigation reference: PR #143, `a77e26ed379097ba31ee649e9970c452e40638eb`.
Implementation: branch `fix/minimal-week5-surface-recovery-v1`, draft PR #144, targeting #142's branch. No automatic merge or deployment.

## Bounded change

Only the fourteen blank 2026 REG Week 5 surfaces are recovered. Each requires matching raw and canonical game IDs, date, teams, actual venue name and raw stadium ID. A nonblank upstream surface is not rewritten. Unlisted games, other weeks, mismatched identities and invalid evidence remain fail-closed. PR #142's active-week isolation and Tuesday 06:00 Denver rollover are preserved.

The evidence registry retains sources, retrieval date, evidence quality, original raw CSV digest and exact source identity. Schedule outputs and the settled manifest retain each applied correction, original surface and evidence digest. No stadium IDs, roof behavior, feature transformations, model/evaluator methodology, betting policy or settlement rules change.

| Canonical game | Actual venue | Recovery surface |
|---|---|---|
| 2026_05_PHI_JAX | Tottenham Hotspur Stadium | artificial; subtype unknown |
| 2026_05_CHI_GB | Lambeau Field | grass |
| 2026_05_CIN_MIA | Hard Rock Stadium | grass |
| 2026_05_LV_NE | Gillette Stadium | fieldturf |
| 2026_05_MIN_NO | Caesars Superdome | sportturf |
| 2026_05_CLE_NYJ | MetLife Stadium | fieldturf |
| 2026_05_IND_PIT | Acrisure Stadium | grass |
| 2026_05_HOU_TEN | Nissan Stadium | matrixturf |
| 2026_05_NYG_WAS | Northwest Stadium | grass |
| 2026_05_DEN_LAC | SoFi Stadium | matrixturf |
| 2026_05_DET_ARI | State Farm Stadium | grass |
| 2026_05_SF_SEA | Lumen Field | fieldturf |
| 2026_05_BAL_ATL | Mercedes-Benz Stadium | fieldturf |
| 2026_05_BUF_LAR | SoFi Stadium | matrixturf |

Each record's provenance is in `config/week5_surface_evidence_2026_v1.json`. Tottenham's raw `JAX00` is retained only as an identity coordinate; the matched venue must be Tottenham, never EverBank. Nissan uses the existing stadium's documented post-2023 Matrix surface, not historical grass or the future replacement stadium. Gillette uses 2026 reinstatement evidence. Caesars and Northwest use their current names and source-category mappings.

## Accepted model behavior

The Totals encoder has separate source-label columns, not a grass/artificial collapse. This correction does not change that encoder. `artificial` marks known artificial class/unknown subtype explicitly; it is not an invented manufacturer mapping. The existing `handle_unknown=ignore` behavior applies when a label is absent from fitted vocabulary. Once this settled row enters subsequent accepted refit history, that vocabulary can include `artificial`; the exception is **not claimed to be prediction-neutral**. No new training procedure, calibration or category-merging rule is introduced.

## Real evidence reconstruction

Current raw schedule digest: `cabed5e312707f28813a023d541ab500df9d52e1f8e502d20cf7e24d37ed971d`.
Original investigation CSV digest: `8b455c694bd589d0c16644438cb7fa8b9f5bde88dcb8fa6721bea03e13c90c02`.

All four required public nflverse sources returned HTTP 200; exact byte counts and hashes are retained in `real-evidence-result.json`. Reconstructed evidence contains 79 real settled games through Week 5, 158 team rows, 182 QB rows and 13,842 PBP rows. The complete Week 5 slate has 15 games: TB–DAL already had a surface and was preserved; the fourteen other rows were recovered.

Offline replay from the retained authentic bytes passed. Real Week 6 materialized with 14 games. Settled games are limited to Weeks 1–5. Fresh real Sleeper collection also succeeded, without fake-session or timestamp overrides.

## Validation commands

```
python -m pytest -q tests/live/test_week5_surface_evidence_2026.py tests/live/test_schedule_materializer_2026.py tests/live/test_schedule_2026.py tests/live/test_evidence_2026.py tests/features/test_totals_v1_context.py
python scripts/validate_week5_surface_recovery_v1.py --output-dir <separate-scratch-directory>
python scripts/collect_sleeper_qbs.py --kind scheduled
python scripts/verify_live_2026_preprovider_v1.py --repository-root <checkout> --schedule-root <offline-replay> --evidence-root <offline-replay> --run-root <authentic-prior-runs> --prediction-as-of-utc <actual-current-UTC>
```

The canonical command is executed through a read-only tracing wrapper that calls the original functions unchanged, strips any Odds-key/token environment names and rejects requests at the session boundary. It records completed stages and exact exceptions. No synthetic settled history, Sleeper fixture or selector history is supplied.

Focused surface/schedule/evidence/context tests: **67 passed**. New-file Ruff and whitespace checks pass. Broader regression and final pre-provider outcomes are recorded separately; unit tests alone do not certify recovery readiness.

No paid provider requests, Odds API access, live market acquisition, VPS access, production publication, timer changes, merge or deployment occurred.

## Final result

**BLOCKED_NFL_EDGE_WEEK6_RECOVERY** — surface recovery succeeded; the canonical pre-provider command subsequently failed closed at missing authentic historical selector evidence.

- Football state completed `2026_REG_W01` through `2026_REG_W05`.
- Football state version: `live-2026-state:731cd471c74c7dec56a052d4`.
- Real Week 6 football scoring completed for all 14 games.
- Football snapshot SHA-256: `1f78d681263c0b712f46520dd337941c3d35fcef2ef4407b10c07874a6b21f65`.
- Actual prediction timestamp: `2026-10-15T15:26:00Z`; source collection occurred before this timestamp. The October 13 timestamp was used only for the separately requested active-week selection check.
- Pre-provider failure: `Entering2026ProductStateError: missing successful final pre-kickoff selector evidence for settled Week 2`, covering all 16 Week 2 games. The exact identities are retained in `preprovider-result.json`.
- No authentic prior-run root was provided in this offline workspace. No selector files were fabricated or reconstructed from outcomes. The empty run-root argument intentionally does not pretend to contain production history.
- Canonical offline preflight network attempts: **0**. Paid provider requests: **0**. Odds API called: **false**. Market data read: **false**.

Smallest next action: supply an export of the existing successful runs' native `run-status.json` and `product/deterministic-proof.json` selector evidence, with provenance and original timestamps. The canonical loader selects the latest eligible evidence strictly before each game's kickoff. It must validate all required weeks; no synthetic backfill or change to selector logic is permitted. Rerun the same offline pre-provider command against that authentic export. No further surface/manufacturer research is required for this approved recovery.

## Broader-test limitation

The wider local live-suite attempt returned 104 passed / 6 failed in 214 seconds. Three failures occurred before the local PyArrow dependency was installed; the subsequent authentic Week 6 scoring now passes that path. The other three hit the pre-existing Task05F historical-board binary SHA gate. A dedicated recheck with the declared numerical library versions and BLAS environment still failed this historical reproduction check (`0660ed395f1df2ef0fc9c8c66d9ed813e75d943218934c623a101ffa0219a946` versus expected `58302290e4dc98d6db13e8e8a46c148e8c58533b2c9930370262982be06ce2a8`). The local interpreter is Python 3.12; CI uses Python 3.11. The cause of that local/CI difference is not established here. No expected hash, historical evidence, numerical method or parity check was changed. The GitHub Market Product workflow passed on the initial implementation commit `85dff4656afb8563609aa7835341933d720b84a7`; final-revision CI is reported separately.

This limitation and the missing native selector history prevent a claim that every recovery gate is green. The surface-specific tests and authentic reconstruction/scoring results stand independently.
