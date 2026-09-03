# NFL EDGE — Live 2026 Market + Product Snapshot V1

Status: implementation milestone for 2026 Week 1 production wiring.

This work does **not** change football-model, evaluator, selector, staking, Play Through,
or Value At methodology.

## Provider and bounded request

Provider: The Odds API v4 current odds endpoint.

The provider's current-odds documentation defines quota cost as:

`number of markets requested × number of effective regions requested`

When `bookmakers` is supplied explicitly, each group of up to 10 bookmakers counts as
one effective region.

NFL EDGE therefore uses one request:

- sport: `americanfootball_nfl`
- bookmakers: `draftkings,fanduel,pinnacle`
- markets: `h2h,spreads,totals`
- odds format: American
- date format: ISO
- commence-time bounds: canonical 2026 Week 1 kickoff envelope only

Expected request cost: **3 credits**.

At two scheduled acquisitions per day this request shape is approximately **6 credits/day**
or **180 credits per 30-day month**, before any manually authorized exceptional acquisition.

Provider reference:
https://the-odds-api.com/liveapi/guides/v4/

## Credit safety

- Live acquisition requires an explicit live gate.
- `ODDS_API_KEY` is read only from the environment/secret surface.
- The key is never written into request metadata or artifacts.
- There are zero automatic retries.
- A successful HTTP response body is persisted byte-for-byte before JSON parsing.
- Parsing, matching, normalization, evaluation, selectors, staking, publication and replay
  must use the saved response after acquisition.
- Ordinary tests and PR CI use only committed synthetic fixture data and consume zero credits.
- Quota headers are recorded when the provider supplies:
  - `x-requests-last`
  - `x-requests-remaining`
  - `x-requests-used`

## Matching contract

Provider events are matched to `data/live/2026/week1_schedule_v1.json` only when:

1. normalized away team matches,
2. normalized home team matches, and
3. commence time is within 15 minutes of the canonical kickoff.

Ambiguous matches and duplicate provider-event mappings fail closed.

The audit distinguishes:

- unmatched provider event,
- unmatched canonical game,
- matched game with no required market offers,
- ambiguous mapping,
- duplicate mapping.

## Market contract

Only these books are normalized:

- `DRAFTKINGS`
- `FANDUEL`
- `PINNACLE`

Only these market families are normalized:

- `MONEYLINE`
- `SPREAD`
- `TOTAL`

Every observation uses the existing `NFL_EDGE_LIVE_MARKET_V1` offer contract and is
validated through `validate_market_board`.

The deterministic synthetic fixture builder at
`tests/live/odds_api_week1_fixture.py` covers all 16 Week 1 games and all three required
books/markets. Its prices are synthetic test values and must never be represented as live
sportsbook prices.

## Replay

A captured response plus its `.meta.json` sidecar is a zero-credit replay input. The
metadata fixes the acquisition timestamp and response hash, so normalization output is
deterministic and can be byte-compared across repeated runs.
