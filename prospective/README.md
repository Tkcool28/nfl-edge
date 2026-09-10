# NFL EDGE Prospective Card Evidence

This directory is the repository authority for **prospective production evidence** captured only after an NFL EDGE canonical product has successfully become production-authoritative.

It is intentionally separate from development backtests, exposed holdout diagnostics, architecture verification, user wager history, and model tuning.

## Evidence model

The tracker preserves two different questions without conflating them:

1. **What did users see at each successful publication?** Every captured canonical product becomes one immutable publication record under cards/<season>/week-XX/publications/.
2. **What was the official pregame recommendation?** official.json is derived from those immutable publications using the last eligible lane state strictly before each referenced game's canonical kickoff timestamp.

Derived files never replace publication history. episodes.json, official.json, results.json, and summary.json are reproducible views that reference source publication IDs and source product hashes.

## V1 schemas

Schemas are stored under schemas/.

- NFL_EDGE_PROSPECTIVE_CARD_PUBLICATION_V1: one successfully published product, all three headline lanes, source product hash/version/provenance, freshness, kickoff context, and deterministic tracking identities.
- NFL_EDGE_PROSPECTIVE_CARD_EPISODES_V1: continuous logical-recommendation episodes and price/line evolution.
- NFL_EDGE_PROSPECTIVE_CARD_OFFICIAL_V1: final eligible pre-kick lane state per referenced game and overlap-adjusted portfolio entries.
- NFL_EDGE_PROSPECTIVE_CARD_RESULT_V1: results attached separately to official records. V1 can remain PENDING until settlement is implemented.
- NFL_EDGE_PROSPECTIVE_CARD_SUMMARY_V1: descriptive lane and deduplicated portfolio summaries.

## Immutable publication contract

The validated NFL_EDGE_PRODUCT_API_V1 artifact is the source of truth for what users saw. The prospective builder hashes that canonical product and copies its headline information without recalculating models, evaluators, selectors, staking, Play Through, or Value At.

Publication records are append-only. The source product SHA-256 is the natural idempotency key. Re-observing the same product does not create a second independent record. An existing immutable path with conflicting evidence raises an append-only violation.

The capture boundary supplies published_at_utc. File mtime is never substituted for canonical generation or kickoff timestamps.

The canonical product currently exposes model_probability, trust_probability, market_probability, EV, support/reliability, units, Play Through, Value At, selector/model/evaluator versions, freshness, and game/model roof state. It does not expose the backend exact-offer evaluator probability overlay. V1 marks that field unavailable instead of inventing it.

## Identity and episodes

V1 keeps three identities for three different purposes:

- **Logical recommendation identity:** lane + canonical game ID + market + canonical normalized selection. Line and price are intentionally excluded so one uninterrupted episode can measure line/price movement.
- **Wager identity:** lane + game + market + normalized selection + line when line defines the wager.
- **Exact offer identity:** game + market + selection + book + line + American odds. This mirrors the current production backend duplicate-suppression identity and excludes lane.

An episode continues only while the same logical recommendation appears in consecutive publications. A different recommendation closes it as REPLACED. A no-card state closes it as DISAPPEARED. If the same recommendation later returns, it starts a new episode with returned_after_gap=true.

Price quality follows the existing bettor convention that larger American odds are better. Line quality reuses production market semantics: larger selected-side spread is better; Over prefers a lower total; Under prefers a higher total. Moneyline has no line-quality metric.

## Official pre-kick definition

Official performance uses the **final valid published lane state strictly before each individual game's kickoff**.

Resolution is per lane and per game, not once for an entire NFL week. That allows a Thursday recommendation to freeze at Thursday kickoff while Sunday and Monday recommendations continue to change.

A publication at or after kickoff is ineligible to replace that game's official state. If a prior BET disappears or the lane points somewhere else before that wager's kickoff, the stale earlier BET is not scored as official. Its historical publication remains preserved.

For an official BET, V1 also records first_appearance so later research can compare early versus final pre-kick price/line behavior.

## Lane history versus portfolio accounting

Hit Rate, Balanced, and Value remain independent selector histories. If two lanes select the same exact wager, both lane histories preserve it.

Combined portfolio accounting deduplicates only an exact offer using the current production identity. Current precedence is hit_rate, balanced, value. The first matching lane owns economic exposure; later matching lanes remain overlap evidence rather than duplicated stake.

## Results and economics

Results are separate from immutable publication files.

V1 initially creates PENDING result references. When settlement is attached later, realized units use the exact official stored American price:

- WIN at positive odds: risked units times odds / 100
- WIN at negative odds: risked units times 100 / absolute odds
- LOSS: negative risked units
- PUSH: 0u
- VOID: 0u unless a later explicit settlement contract changes it

ROI is net units divided by units risked. Hit rate is wins divided by wins plus losses, so pushes and voids do not inflate the hit-rate denominator.

Persistence rebuilds pending identities from the official card while preserving any already-settled result row with the same stable identity. A settled row that would disappear from regenerated official evidence causes a fail-closed persistence error rather than silent historical rewriting. Mixed settled/pending weeks are labeled PARTIAL.

## Runtime capture

The production refresh accepts an optional `--prospective-dir`. When configured, the sequence is strictly `publish -> re-read authoritative latest -> capture`. Candidate products that fail publication are never captured. The same canonical product encountered twice is deduplicated by source-product hash, preserving the first immutable publication timestamp.

Native runtime evidence is written under `/var/lib/nfl-edge/prospective_card_log_v1/<season>/week-XX/publications/`. Capture is observational and requires zero additional sportsbook-provider calls. Capture failure is recorded in refresh status but does not roll back a product that already published successfully.

The production systemd contract grants write access only to the existing refresh/product roots plus `/var/lib/nfl-edge/prospective_card_log_v1`. It does not alter the twice-daily timer, provider credential, backend service, or HTTP surface.

## Repository persistence

Repository persistence is implemented as a separate worker and is deliberately not part of the public HTTP backend or product publisher.

The intended production sequence is:

1. production refresh publishes the canonical product;
2. post-publication capture writes immutable runtime evidence under `/var/lib/nfl-edge/prospective_card_log_v1/`;
3. a dedicated persistence invocation reads one season/week from runtime staging;
4. every runtime publication is validated against the checked-in Draft 2020-12 publication schema and V1 privacy/provider invariants;
5. immutable publications are copied into an isolated evidence worktree under `prospective/cards/<season>/week-XX/publications/`;
6. episodes.json, official.json, results.json, and summary.json are deterministically regenerated and schema-validated;
7. the Git wrapper stages only `prospective/cards`, verifies every staged path remains below that prefix, commits, and pushes only the configured evidence branch.

The wrapper refuses to run if the evidence worktree is dirty before sync or is checked out on any branch other than the configured evidence branch. It fast-forwards from the matching remote branch before copying evidence and fails rather than force-pushing or rewriting divergent history.

The production `/root/nfl-edge` checkout is therefore read-only from the persistence worker's perspective and should remain clean. The suggested evidence worktree location is `/var/lib/nfl-edge/prospective_git_v1/worktree` on a dedicated `prospective-evidence-v1` branch.

Git credentials are not accepted as CLI arguments or stored in the tracked environment example. The worktree's `origin` must already be authenticated through the VPS's approved trusted Git mechanism using least privilege. Tokens/keys must remain outside the repository and logs.

The repository includes a hardened oneshot systemd service contract for this worker, but activation is intentionally deferred until the VPS worktree, remote authentication, permissions, and current production state are inspected after merge. No persistence timer/cadence is introduced repo-side in V1.

## Privacy and safety

Prospective evidence contains no usernames, session IDs, credentials, bankrolls, personalized dollar stakes, or user wager history. Canonical recommendation units are product-level evidence and are intentionally retained.

The tracker is observational only. Early prospective results do not alter model methodology, evaluator thresholds, selector policy, staking, pricing ceilings, Play Through, Value At, roof semantics, market acquisition, or production product generation.

## Native evidence boundary

Do not fabricate contemporaneous history. The first native prospective timestamp will be documented only when runtime capture actually becomes operational.

Any later import of archived pre-activation production artifacts must be explicitly labeled RECONSTRUCTED_FROM_ARCHIVED_PRODUCTION_ARTIFACT rather than NATIVE_PROSPECTIVE.

## Planned evidence layout

    prospective/
      README.md
      cards/
        2026/
          week-01/
            publications/
              <generated-at>--<source-product-hash-prefix>.json
            episodes.json
            official.json
            results.json
            summary.json

A future current-card pointer and NFL_EDGE_DAILY_NEWS_BRIEF_V1 may consume these records, but News implementation is outside this milestone and immutable publication files remain historical authority.
