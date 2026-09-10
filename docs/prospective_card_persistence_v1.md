# NFL EDGE Prospective Evidence Persistence V1

## Purpose

Persist native prospective card observations from production runtime storage into Git without allowing the public backend or the production `main` checkout to write repository history.

This is evidence plumbing only. It does not change or invoke models, evaluators, selectors, staking, Play Through, Value At, sportsbook acquisition, or user state.

## Paths and branch

- Production code checkout: `/root/nfl-edge`
- Runtime observations: `/var/lib/nfl-edge/prospective_card_log_v1`
- Isolated evidence checkout: `/var/lib/nfl-edge/prospective_repo_v1`
- Remote evidence branch: `ops/prospective-card-evidence-v1`

The persistence service treats `/root/nfl-edge` and runtime observations as read-only. Only the isolated evidence checkout is writable.

## Runtime sequence

The existing production refresh remains at `00:05 UTC` and `12:05 UTC`. After successful canonical product publication it writes immutable native evidence. The separate non-billable persistence timer runs at `00:20 UTC` and `12:20 UTC`.

The persistence worker requires the exact evidence branch, refuses detached/dirty/diverged state, never automatically merges or rebases, validates runtime publications, copies exact immutable bytes, regenerates derived episodes, finalizes eligible weeks, stages only `prospective/cards/**`, refuses unrelated changes, commits, and performs a normal non-force push to the evidence branch. It never pushes `main`.

## Week finalization

Every native publication stores `source_week_last_kickoff_at_utc`, derived from the full canonical product game board. The persistence worker uses the most conservative captured boundary for a week and finalizes only when current UTC time is strictly later.

Finalization creates `official.json`, initial `results.json` with PENDING grades, and `summary.json`. Official and initial result records are append-only. Later post-kick publications may extend history without rewriting the official wager set. A recovered pre-kick record that would change finalized official performance raises an append-only violation and requires explicit correction handling.

## Provider and privacy boundary

Additional Odds API calls: `0`.

Additional Odds API credits: `0`.

Evidence must state `provider_calls=0` and `user_specific_data_included=false`. Do not store usernames, sessions, password hashes, bankrolls, personalized dollar stakes, user wager history, provider credentials, or Git credentials.

Git authentication must use an existing least-privilege VPS credential or secret store. Never commit or print a token.

## Post-merge VPS deployment

Do not deploy this branch before it is reviewed, green, and merged.

1. Verify `/root/nfl-edge` is on clean `main`, then fetch and fast-forward to the exact reviewed merge commit.
2. Ensure remote `ops/prospective-card-evidence-v1` exists.
3. Create the runtime and isolated evidence directories with bounded permissions.
4. Clone the repo into `/var/lib/nfl-edge/prospective_repo_v1` and check out exactly the evidence branch.
5. Configure a non-secret Git author identity and existing least-privilege Git authentication in that isolated checkout.
6. Install the reviewed production-refresh unit update plus the prospective persistence service/timer and run `systemd-analyze verify`.
7. Keep the existing production refresh schedule unchanged and use zero-credit fixture/replay acceptance first.
8. Enable the persistence timer only after acceptance. Do not manually invoke a billable `--live` refresh solely to create evidence.
9. Observe the next ordinary scheduled successful production refresh and record the exact first `NATIVE_PROSPECTIVE` timestamp and source hash.
10. Observe the following persistence cycle, verify identical bytes reached the evidence branch, verify `/root/nfl-edge` stayed clean, and verify the backend was not restarted by this feature.

The first native timestamp is the prospective evidence boundary. It must come from activated runtime capture, never from reconstruction or a fixture.

## Failure behavior

A production capture failure is visible but does not reverse successful product publication. A repository persistence failure affects only the separate oneshot and never changes production product availability.

If the evidence checkout diverges, contains unrelated changes, or hits an append-only conflict, stop and reconcile manually. Do not use automatic merge, rebase, force-push, `git clean`, or history rewriting.

## Repository acceptance

CI must prove deterministic/idempotent capture, full-week boundary preservation, post-publication ordering and failure isolation, exact byte copying, idempotent persistence, prospective-only Git commits, unchanged production checkout status, wrong-branch rejection, safe week finalization, finalized-official drift protection, and zero provider calls.

VPS acceptance remains separate because repository CI cannot truthfully establish the first native production timestamp or actual VPS service/filesystem state.
