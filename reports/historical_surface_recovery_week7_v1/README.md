# Permanent historical surface recovery and Week 7 hardening V1

Starting GitHub main: `02c733017e8562265178c3ee377b2a0d784945f0`.
Branch: `fix/historical-surface-recovery-week7-v1`.

Repository implementation, regression testing, free-source acquisition and offline validation only. VPS access was limited to original evidence reads and hashes. No VPS modifications, deployment, production refresh, paid request, merge, or publication.

## Diagnosis and existing work

Remote main was independently verified using `git ls-remote` before editing. Main includes merged #142 and #144. Open #143 is investigation-only, #117 concerns presentation/evaluator economics, and #78 concerns a separate governed holdout run; none implements this correction. The eight PR-triggered workflows associated with #144 final head `79ef9555ea2c904bad243004a9c9b8dd2fa68c76` reported success. That historical CI is not presented as CI for this new branch.

`original-failure.txt` records the unmodified starting materializer rejecting a blank SEA–DEN surface. The Week 5 helper returned no evidence outside Week 5. `evidence_2026.py` then built every prior schedule before writing the active schedule, and built all historical schedules a second time for its ID comparison. Thus a historical metadata problem prevented an independently complete Week 7 slate from being written.

## Changes and trust boundaries

- `surface_evidence_2026.py` adds a reusable exact-game 2026 REG evidence registry. Each additional record requires raw/canonical game IDs, date, season/week, teams, venue/name ID, explicit class/subtype certainty, HTTPS sources, retrieval date, evidence quality, description, and a checked deterministic digest. No default surface is introduced. Existing Week 5 records, provenance formatting, and Tottenham artificial/unknown-subtype handling remain unchanged.
- SEA–DEN has one independently established `grass` record. The official Seahawks calendar and stadium event page identify the October 15 Week 6 game at Empower Field; the current operator's field description identifies grass. No cultivar/manufacturer claim is made. URLs and retrieval date are retained in the registry.
- `historical_schedule_2026.py` introduces content-addressed replay bundles containing the original allowed source fields and fully validated canonical schedule. The successful settled-evidence manifest binds each eligible bundle by SHA-256. An arbitrary existing schedule is not a trusted cache. Source identity, complete slate, date/kickoff/rest/venue/location, provenance, content digest and exact reproduction by the current materializer must all agree. A newly blank historical surface may reuse validated context; a conflicting nonblank surface rejects reuse.
- Canonical roof structure/context must agree. The existing materializer intentionally maps retractable OPEN/CLOSED positions to identical pending canonical context. Those equivalent source values may differ; fresh actual roof position is still taken from the settled results, unchanged. A structural roof change fails closed.
- Historical-only bootstrap: an independently reviewed, pinned Week 6 bundle permits legacy recovery without trusting naked runtime files. No other upstream archived week is approved. Active-week materialization never uses this archive fallback.
- `evidence_2026.py` validates and writes the active schedule independently; historical reconstruction and football-state gates still block dependent publication. It reuses eligible checkpoints or strictly rebuilds history, checks settled coverage against those same schedules without decoding them twice, and issues checkpoints only after required results/stats/PBP checks pass. Readers verify checkpoint integrity and replay compatibility before returning evidence. Per-file atomic writes and the shared reader/writer lock remain in place.
- The canonical pre-provider CLI now returns structured blocked-stage errors for schedule, historical evidence/replay, state advancement, Sleeper, scoring and historical selector evidence. Existing production-refresh outcome distinctions and the paid-provider ordering are unchanged. There is no catch-and-continue path into acquisition or publication.
- The football CI workflow explicitly includes the new historical recovery, preserved Week 5 and settled-evidence regressions.

## Immutable Week 6 proof

A read-only VPS read independently hashed the original schedule at `/var/lib/nfl-edge/live_inputs_v1/2026/week6_schedule_v1.json`:

`8a2ace347b2d2fbe0c0c08d50cbe803efbba26b6ec4e63cf1802e3b90dc2e76e`

It was verified at `2026-10-16T00:01:01Z`. The original successful `refresh-20261016T000503.505703Z` status references that exact schedule version and records publication. These are existing historical operations, not operations performed by this task.

The latest upstream games.csv commit before that verification timestamp was:

`03c626d725fcead747f8ce2b2c86110c4d6ff1b7` (`2026-10-15T23:15:13Z`).

Immutable source URL:
https://raw.githubusercontent.com/nflverse/nfldata/03c626d725fcead747f8ce2b2c86110c4d6ff1b7/data/games.csv

Acquired raw SHA-256:
`bef567a464e55c0ff0ba235a55763cbfdb480fa496860f076ed4a6f3f5383e93`

The current materializer, using that source's Week 6 projection and the original timestamp, reproduces the saved schedule **byte-for-byte** with the independently observed original SHA above. Only that verified Week 6 projection is pinned. The archive is not a license to restore unverified surfaces from other weeks. Full game/venue/current-source compatibility is checked on every reuse.

Pinned replay bundle digest:
`be5817e96de05f363b23d58c0c2b6888ad911c5f9e4b71643a498d2face1ea5c`

## Consumer audit

| Consumer | Required history | Result |
|---|---|---|
| Settled reconstruction | Every completed game's canonical identity, final result, team/QB stats and terminal PBP | All existing checks remain mandatory; no skipped historical games |
| Football-state advancement | Historical schedule contexts plus genuine settled results/statistics/PBP | Advances all W01–W06 blocks; reusable venue metadata does not substitute football evidence |
| Deterministic replay | Original context, provenance, source identity and unchanged materializer output | Checked content-addressed bundles; exact replay required |
| Pre-provider validation | Complete active schedule, complete history/state, fresh Sleeper, scoring and native causal selector evidence | Original gates retained; structured blocked-stage diagnostics added |
| Publication | Existing evaluator/provider/publication stages after pre-provider gates | Production ordering/outcome codes unchanged; no publication invoked |

## Regression and authentic evidence

Regression suite: **113 passed** (`regression-tests.txt`).
Roof/scenario/settled Totals/selector compatibility: **20 passed** (`compatibility-tests.txt`).
Ruff, changed-module compilation, and `git diff --check`: passed.

Coverage includes original SEA–DEN shape, exact evidence recovery and identity/digest/provenance conflicts; trusted historical replay and naked-file rejection; complete slate/hash/replay incompatibility failures; unresolved active surfaces; missing PBP/results; London unknown-subtype preservation; aliases/blank roofs; equivalent retractable actual positions; Week 7 Tuesday rollover; frozen-input determinism; and zero-request failure before pre-provider gates. A regression also preserves Week 5 recovery provenance ordering during replay, even when current source rows are reordered.

Authentic current nflverse acquisition has all 14 Week 6 surfaces blank, not just SEA–DEN. `pre-archive-validation-blocker.json` records the strict failure on the next unresolved game before the approved archive bootstrap existed; it is superseded by the successful recovery below.

Settled reconstruction: **93 games through Week 6**, **186 team rows**, **211 QB rows**, **16,380 PBP rows**. Two network-denied materializations from the same authentic acquired bytes and frozen observation time produce identical manifests and all four data frames. No fixture inputs were used for authentic validation.

Settled manifest SHA-256:
`26982a93435c268033a12e1f7c271d88718a5adbfa4042f38902c02b4bc82583`

Fresh real Sleeper collection succeeded. Week 7 schedule selection and coverage contain 14 games. Source acquisition records retain HTTP status, acquisition timestamps, raw byte counts and SHA-256 values.

The previously recovered Weeks 2–5 native selector archive has outer SHA-256:
`5542d81c656ac2e18d1056a1680cbfb6c7f731db0212692ee304b63496a100e4`.
Every internal SHA256SUMS entry was verified before use. Extraction rejected links, special files and escaping/absolute paths.

Four additional original Week 6 final pre-kickoff snapshots and their statuses were read from the VPS without modification. Their local bytes match the independently reported server SHA-256 and size. The run inventory identifies all successful candidates over the Week 6 interval; the selected originals cover SEA, Sunday daytime, Sunday night and Monday night at each game's latest successful pre-kickoff snapshot. Original historical provider counters in those statuses are not requests made by this task.

Native selector coverage validated by the unchanged canonical assembler: Week 2: 16 games/96 rows; Week 3: 16/96; Week 4: 16/96; Week 5: 15/90; Week 6: 14/84. Row digests are retained in `native-selector-coverage.json`. No evaluator rows were regenerated from outcomes.

## Canonical validation

The unchanged production functions run through `scripts/verify_live_2026_preprovider_v1.py`, with the real evidence root, fresh collected Sleeper source and authentic native run root. A read-only wrapper records completed stages and denies all HTTP requests. No sportsbook acquisition or production refresh is invoked.

Final canonical result and classification are recorded in `preprovider-result.json` and `final-result.json`. Unit tests alone do not establish Week 7 readiness. No merge or deployment is authorized by these results.
