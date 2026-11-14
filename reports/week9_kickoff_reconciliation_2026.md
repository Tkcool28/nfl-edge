# One-time 2026 REG Week 9 LV@SF historical source reconciliation

Base: independently verified GitHub main `3490e93f27c2a9bd835a4582cc82cab80f6111fd`, merged PR #146. Implementation is in a separate clone, not the deployed `/root/nfl-edge` checkout.

## Official evidence

NFL game page: https://www.nfl.com/games/raiders-at-49ers-2026-reg-9

Official gamebook linked by that page: https://static.www.nfl.com/image/upload/v1794224923/gamecenter/ab581766-4feb-11f1-abca-2c54536568a9.pdf

Downloaded PDF SHA256: `0e1895910aefbeda55a1a93ea670e5adebccc040a16c86a25d90534186dbec42`. Its first page identifies Sunday 11/8/2026, Las Vegas Raiders at San Francisco 49ers, Levi's Stadium, Santa Clara, and Start Time 1:25 PM PST. That is 16:25 Eastern / 21:25 UTC, not the archived 16:05 Eastern / 21:05 UTC.

Independently fetched https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv SHA256: `8b1e7522bf9aa5cfa78b6f61e2d1735a39b5c9c5a602bc7549304d6bafeac26b`; exact row `2026_09_LV_SF`, season 2026, REG week 9, 2026-11-08, LV away, SF home, Levi's Stadium / SFO01 has `gametime=16:25`.

These public sources were fetched for research only, outside network-disabled tests. No Odds API, paid provider, or Sleeper acquisition was used.

## Deliberately limited semantics

The archived schedule was verified at `2026-11-06T00:01:01Z`, before the game. Its kickoff is pregame schedule context, not proof of what was known at prediction time later, nor the product's `prediction_as_of_utc`. Replacing kickoff while retaining that November 6 as-of would backdate corrected knowledge. Therefore this change accepts the exact upstream discrepancy, but returns the ORIGINAL immutable bundle and schedule, including 21:05 UTC and the original as-of. It does not publish a corrected schedule, recalculate forecasts, modify prospective cards, or move any cutoff to 21:25 UTC. Consumers continue to use the frozen earlier cutoff; accepting this discrepancy does not authorize newly eligible late inputs.

The exception exists only inside historical `reuse()`, pinned to original checkpoint content digest `b35fb2e0cabb01ef7d829e447c53918c69fe2922c76eabe908bb5c2f7b6cb191`, and exact season/type/week/game/date/teams/venue and old/new `gametime` values. All other checks remain unchanged, including replay reproduction, source URL, manifest identity, slate completeness, rest, location, roof and surface. The existing blank-surface/equivalent-roof allowances are neither extended nor removed. Synthetic or re-addressed bundles do not qualify.

The test fixture is an unmodified byte copy of that actual original checkpoint: file SHA256 `214603b8bdc065f71f95c7906ca60d04f0994259bbc24e717b1caa5002c6da17`, 14294 bytes. Canonical content digest and physical-file hash are distinct. No original archive is edited.

## Validation results and CI caveat

Fresh final validation: 83 tests passed with the entire pytest process in an `unshare -n` network namespace, explicit isolated-source `PYTHONPATH`, disabled bytecode/cache writes, and a scratch-only pytest base directory. Ruff passed for both changed Python files; whitespace checks passed. All 40 protected runtime/archive/publication files matched the retained byte lengths and SHA256 inventory before validation. The retained official PDF was independently rehashed and its first page re-extracted; its hash and 1:25 PM PST passage match the evidence above.

The commit deliberately includes `[skip ci]` to prevent push/pull-request GitHub Actions execution: existing unfiltered PR workflows include a real Sleeper proof. No workflow or repository setting is changed. Skipped/pending-required CI is not green CI; local offline results are the validation evidence for this draft. Independent final review is reserved for ChatGPT separately. No full suite or production integration replay is claimed.

## Validation boundary and remaining work

The new offline tests exercise real `reuse()` and its real materializer reproduction over the full 15-game original checkpoint. They prove repeated acceptance without writes or input mutation, preserved kickoff/as-of, rejection for other identity/context fields, other times, other games and altered originals (including recomputed digest), and preservation of the existing blank-surface rule. The older synthetic LV@SF conflict test remains fail-closed. Existing historical replay tests cover provenance, completeness, incompatible payloads, required PBP/results, and active-week separation.

Run scoped tests with `unshare -n /root/nfl-edge/.venv/bin/python -m pytest -q tests/live/test_week9_kickoff_reconciliation_2026.py tests/live/test_week9_week10_surface_evidence_2026.py tests/live/test_historical_surface_recovery_2026.py`. The namespace disables network for the entire test process; new tests also reject requests and socket connections. Lint the changed Python files with Ruff and run `git diff --check`.

No production replay, deployment, runtime writes, service/timer operations, model fitting/state advancement, or publication is part of this PR. Separately authorized work must merge/deploy reviewed code, qualify actual complete Week 9 settled results/team/QB/PBP inputs through the canonical orchestration, advance frozen model state only after all settlement gates pass, and separately qualify any subsequent prospective publication and provider budget. This metadata replay test is not evidence that Week 9 settlement or model advancement has completed. A requirement to expose corrected kickoff in derived historical outputs would be a separate task with explicit provenance/as-of semantics, not this archive-preserving exception.
