# Historical Market Acquisition — Manifest & Dry-Run Plan (Task 05E-C3)

Operator documentation for the **RAW-only** preparation of the authoritative
2020–2024 historical sportsbook acquisition for NFL EDGE.

**Scope:** freeze the market-source manifest, deterministically generate the
575-row T-60 request plan, and provide safe, resumable acquisition tooling.
**This is setup/review only. It performs ZERO Odds API calls and writes no
normalized sportsbook tables.** `2025` stays fully sealed.

---

## 1. Architecture firewall

```
FOOTBALL MODEL -> independent estimate -> MARKET DATA ->
model-vs-market disagreement -> edge research/recommendation
```

Historical sportsbook data is **downstream-only**. It must never become a
feature or training input to any frozen football model (Oracle QB-Elo,
XGBoost, Expected-Margin, Ridge Totals). No outcome inspection, no
edge-bucket scoring, no retuning. This package only *prepares RAW
acquisition*.

## 2. Source & scope

| item | value |
|---|---|
| Provider | The Odds API (historical NFL odds endpoint) |
| Sport | `americanfootball_nfl` |
| Coverage | **2020–2024 only** |
| Kickoff source | `data/raw/source_snapshots/v1/schedules_2018_2025_frozen-baseline-v1.parquet` |
| Kickoff fields | nflverse `gameday` + `gametime`, interpreted in `America/New_York` |

2018–2019 are recorded as **unresolved** (authoritative sportsbook history
unavailable). nflverse market-like fields must NOT be substituted as
authoritative history. If 2018–2019 remain unavailable before edge scoring,
the future preregistered split becomes **discovery: 2020–2022** and
**confirmation: 2023–2024** — recorded but not scored in this task.

## 3. Canonical T-60 snapshot rule (frozen)

Per gameday:

1. Sort actual kickoff timestamps (UTC, DST-aware from Eastern).
2. Form deterministic *natural kickoff clusters*; a cluster spans at most
   **30 minutes** from its earliest kickoff.
3. Anchor the request at **earliest kickoff − 60 minutes**.
4. The Odds API may return the nearest snapshot **at or before** the
   requested timestamp.
5. Persist **both** `requested_target_timestamp_utc` and
   `actual_snapshot_timestamp_utc`. Later canonical use keys on the actual
   returned snapshot, never pretending it is exactly T-60.

Accepted counts (reproduced by `build_historical_market_request_plan.py` or
the build fails closed):

* 575 total requests/clusters
* 2020=107, 2021=111, 2022=116, 2023=120, 2024=121
* 1,408 games, each in exactly one cluster
* observation lead always in **[60, 90] minutes**

## 3. Frozen bookmaker set (exact)

| Role | Keys |
|---|---|
| Actionable retail | `draftkings`, `fanduel` |
| Primary sharp / market benchmark | `pinnacle` |
| Secondary independent reference | `betonlineag` |
| Other consensus input | `williamhill_us`, `betmgm`, `betrivers`, `bovada`, `lowvig`, `betus` |

Markets: `h2h`, `spreads`, `totals`. No other books/markets are added.
Historical absence is valid data; per-book data is preserved (never replaced
by a consensus-only value). No outcome-based weighting.

## 4. Credit contract

* 10 books × 3 markets = **30 credits** per successful request
* 575 requests → **17,250 credits** planned
* `INITIAL_PLANNED_CREDIT_CAP = 17250`
* **No automatic retries**
* STOP if any success reports `x-requests-last != 30`

## 5. Runner usage

```bash
# Dry-run: ZERO API calls, ZERO credential access (default)
python scripts/run_historical_market_acquisition.py

# Explicit live gate (requires ODDS_API_KEY; single secret, never enumerated)
python scripts/run_historical_market_acquisition.py --execute
```

Default behavior is always safe (dry-run). Only `--execute` opens the network
path, and it reads only `ODDS_API_KEY` (a direct `os.environ.get`, never an
`os.environ` enumeration). Request URLs are redacted before any persist/log.

## 6. Resume / idempotency

* Every plan row has a stable, deterministic `request_plan_id`
  (`md_<season>_<nnn>`).
* Before issuing, the runner checks whether that id already has a **verified
  successful raw + hash/ledger match**; if so it is skipped (no re-spend).
* After a success: write temp → fsync → hash → atomic move to immutable raw
  → atomically record ledger. A crash never causes a known-completed snapshot
  to be re-queried.
* A bounded acquisition lock (`data/market_data/lock/acquisition.lock`) is
  used to prevent concurrent workers.

## 7. Raw immutability

RAW → NORMALIZED → CANONICAL remain distinct. Raw API payloads are never
rewritten once persisted (`write_raw_immutable` refuses an existing path).
A sidecar ledger holds metadata (timestamps, status, cost headers, response
hash, redacted URL). Normalization later never mutates raw.

## 8. Secret safety

* Never persist `ODDS_API_KEY`, any API-key value, Authorization secrets, or
  full env dumps.
* Request URLs in any ledger/log are fully redacted (`apiKey=REDACTED`).
* A regression guard hard-fails if a secret token or the supplied key value
  would be persisted.

## 9. Where the artifacts land

| artifact | path |
|---|---|
| Frozen manifest (machine-readable) | `data/manifests/historical_market_acquisition_v1.json` |
| 575-row request plan | `data/manifests/historical_market_request_plan_v1.parquet` |
| Plan SHA-256 + meta | `data/manifests/historical_market_request_plan_v1.json` |
| Raw payloads (future) | `data/market_data/raw/{season}/{request_plan_id}.json` |
| Ledger (future) | `data/market_data/ledger/historical_acquisition_ledger_v1.parquet` |

## 10. Operator contract — where the real pull may run

**Do NOT launch the 17,250-credit acquisition from a disposable worktree.**
The real `--execute` pull must be run only from the intended durable
production checkout **after this feature branch has been reviewed, merged,
and synchronized into it**. A disposable worktree is not a durable home for
paid raw payloads or the resume ledger.

* Raw historical payloads and the acquisition ledger must live in the durable
  canonical repo/data location intended for later normalization
  (`data/market_data/raw/...`, `data/market_data/ledger/...`), not in a
  throwaway checkout that could be removed.
* The 17,250-credit run is **irreversible spend**; the operator must confirm
  the checkout is the production checkout before `--execute`.

## 11. Live-run safety (pre-pull remediation)

Before `--execute` issues any network call it now, in order:

1. **Validates the runtime plan contract** (`run_live_acquisition`) — rows
   575, seasons 2020–2024, per-season 107/111/116/120/121, unique
   `request_plan_id`, 1,408 games with no duplicates, no 2025, bookmaker
   allowlist == frozen 10, markets `h2h,spreads,totals`, credit projection
   17,250, and the request-plan SHA-256 ==
   `1591542e16cfeaa7eeef6d6e04a87db00c67ec8b988b1559c6645b9a06d20e4a`.
   Any violation → stop before network.
2. **Acquires an exclusive fail-fast lock** — a second concurrent `--execute`
   worker is blocked before any API call.
3. **Classifies every request id** against the ledger: `VERIFIED_SUCCESS`
   (skip), `PAID_REJECTED` (stop, operator remediation required, never
   re-query), `REQUEST_FAILED` (stop, no automatic retry), else eligible.
4. **Enforces the credit ceiling** — projected max = remaining eligible × 30,
   capped at 17,250, reported before executing.

Every paid 2xx response is preserved immutably and ledgered **before** any
post-response validation, so a paid-but-invalid response is never lost and
never repurchased.