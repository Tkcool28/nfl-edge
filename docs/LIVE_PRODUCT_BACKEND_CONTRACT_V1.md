# NFL EDGE — Live Product Backend Contract V1

**Contract identity:** `LIVE_PRODUCT_BACKEND_CONTRACT_V1`  
**Public product schema:** `NFL_EDGE_PRODUCT_API_V1`  
**Production architecture anchor:** `91e7362aca589179ab4c8f92009315a26bb45faf`  
**Architecture evidence:** `reports/architecture_verification/post_v5_v2_2020_2025/`

This document freezes the interfaces by which the already-frozen Post-V5 V2 football architecture becomes a live product. It does **not** change QB-Elo, XGBoost V2, Expected Margin, Ridge Totals R4, evaluators, confidence/trust, selectors, units, risk profiles, Play Through, or Value At.

> The frontend consumes the product/API contract. It does not consume internal model files directly.

> The API serves already-generated product state. User requests do not train models.

The intended runtime topology is:

`scheduled scorer -> complete validated product snapshot -> atomic latest promotion -> API -> frontend`

A browser/API request never trains or directly rescales/rescores football models.

## 1. Versioning and null semantics

`NFL_EDGE_PRODUCT_API_V1` is the compatibility boundary. Fields marked required by the checked-in JSON Schema are always present. A required field may be explicitly `null` only when the schema permits it and the producer genuinely lacks that value; null is never a fabricated replacement.

Breaking field removal/renaming, enum narrowing, or semantic reinterpretation requires a new schema identity (`..._V2`). V1 producers may add a new producer/product version while remaining schema-compatible. Timestamps are RFC3339 UTC strings ending in `Z`.

All numeric contract values must be finite. `NaN`, positive infinity, and negative infinity are invalid contract values even if a language runtime can represent them. Published JSON is serialized with non-finite values forbidden.

Canonical implementation files:

- `schemas/NFL_EDGE_PRODUCT_API_V1.schema.json`
- `src/nfl_edge/contracts/live_product_v1.py`
- `src/nfl_edge/publication/live_product_v1.py`
- `fixtures/contracts/nfl_edge_product_api_v1_week1_mock.json`

## 2. Product snapshot

Top-level required metadata:

- `schema_version = NFL_EDGE_PRODUCT_API_V1`
- `product_version`
- `generated_at_utc`
- `prediction_as_of_utc`
- `season`, `week`
- `slate_status`: `UPCOMING | ACTIVE | COMPLETE | OFFSEASON`
- `football_data_version`
- `qb_snapshot_version`
- `market_snapshot_version`
- `model_versions`
- `evaluator_versions`
- `selector_versions`
- `freshness`
- `stale`
- `warnings`
- `headlines`
- `games`

`stale` is an explicit compatibility convenience and must agree with `freshness.state == STALE`.

## 3. Headline lanes

The product always contains distinct `hit_rate`, `balanced`, and `value` objects. Each object has a canonical `lane` (`HIT_RATE`, `BALANCED`, `VALUE`) and one state:

- `BET` — an actionable headline exists now.
- `NO_PLAY` — the lane is supported but honestly has no current play.
- `TARGET_ONLY` — a named offer/target may be shown but is not currently a bet.
- `SUPPRESSED` — a candidate exists but product policy suppresses publication/action.
- `UNSUPPORTED` — required evidence/model support is unavailable.

Every headline object carries fields for game/matchup, market, selection, book, line, American odds, model probability, trust probability, market probability, EV, support, reliability, recommended units, Play Through, Value At, and warnings. Non-actionable states may carry null offer/probability fields when the value genuinely does not exist.

`recommended_units` remains the frozen account-independent unit result. The product contract does not derive a different recommendation because of user bankroll/profile.

## 4. Full game board

Every current NFL game is representable with:

- canonical `game_id`
- `season`, `week`
- `home_team`, `away_team`
- `kickoff_at_utc`
- `game_status`: `SCHEDULED | PREGAME | IN_PROGRESS | FINAL | POSTPONED | CANCELLED`
- optional `venue`
- `neutral_site`
- `updated_at_utc`
- both team QB contexts
- live market board
- frozen football model outputs/statuses
- warnings

### QB context

Each side requires: team, game ID, expected starter, Sleeper player ID, canonical NFL EDGE QB ID, GSIS ID where available, depth designation, injury status, source, source snapshot time, provenance ID, resolver status, explicit freshness, warning state, and last-change time.

Resolver statuses:

`RESOLVED | NEW_PLAYER | UNRESOLVED | AMBIGUOUS | MISSING_EVIDENCE | OVERRIDDEN`

Unresolved/ambiguous/missing evidence is legal product state and must remain explicit. It is never silently converted to a resolved starter.

### Market board

Each game contains separate `moneyline`, `spread`, and `total` maps. Within each map, only observed books are present. Allowed observed books are:

`DRAFTKINGS | FANDUEL | PINNACLE`

`BOOKS` therefore means the observed market-board set. The actionable retail subset is separately frozen as `RETAIL_BOOKS = {DRAFTKINGS, FANDUEL}`.

A missing book key means **no usable observation from that book**. It must not be filled from another book or synthesized.

Each exact offer contains provider/source, game identity, sportsbook, market type, selection, line, American price, snapshot timestamp, normalized selection, exact offer ID, and explicit freshness. Moneyline `line` is null; spread/total line is numeric.

## 5. Exact-offer evaluation

### Request — `NFL_EDGE_EXACT_OFFER_V1`

Required:

- `game_id`
- `market_type`
- `selection`
- `book`
- `line` (`null` only for moneyline)
- `price`

For the public/actionable V1 request, `book` must be one of:

`DRAFTKINGS | FANDUEL`

Pinnacle observations remain legal on the market board as sharp benchmark evidence, but `POST /api/v1/evaluate-offer` does **not** accept `PINNACLE` as a user/actionable exact-offer book. V1 defines no separate diagnostic-only Pinnacle request path.

### Response

Required:

- `supported`
- probability
- trust probability
- break-even probability
- EV
- verdict
- recommended units
- Play Through
- Value At
- warnings

A clicked stored sportsbook offer and a manually typed offer use the **same request shape and same evaluation path**. Manual entry is provenance/presentation only; it does not choose a different evaluator. The existing `recommendation/product_policy_v1.py` contract remains authoritative: default/game-detail/manual evaluation uses the Balanced philosophy and the frozen Task05F evaluator + Play Through + staking path. A changed spread/total line is a new exact offer; no synthetic line conversion is permitted.

## 6. Live football scorer — `NFL_EDGE_LIVE_SCORER_V1`

The scorer is prospective and market-independent.

### Inputs

The scheduled scorer receives/version-identifies:

- current NFL schedule
- `prediction_as_of_utc`
- completed historical football state and `history_complete_through_utc`
- current QB state
- resolved expected starting-QB state
- frozen model artifact/config versions
- required feature/state versions

`history_complete_through_utc` must not be later than `prediction_as_of_utc`. Completed-game QB performance may update future QB state only after the completed game is inside the historical state. Current-game information cannot update that game's own pregame prediction.

**Sportsbook prices are prohibited scorer features.** Market acquisition/evaluation happens downstream of football inference.

### Per-game outputs

The product records status/output for:

- QB-Elo
- XGBoost V2
- Expected Margin
- Ridge Totals R4

Ordinary model outputs contain:

- `status`: `AVAILABLE | UNAVAILABLE | UNSUPPORTED | FAILED | STALE_INPUT`
- prediction (nullable when unavailable)
- support state
- input/provenance identity
- artifact version
- warnings

One unavailable model is represented honestly; it is not fabricated. Downstream evaluator/selector/product generation must consume the support/status and fail closed where its own prerequisites are not met.

### Pending retractable-roof XGBoost state

For a retractable-roof game whose official roof state is still unresolved, XGBoost remains model-available through the distinct V1 status `AVAILABLE_WITH_ROOF_SCENARIOS`. This is not a singular selected prediction. The contract requires:

- `prediction = null`
- `support = PARTIAL`
- `roof_resolution_status = PENDING`
- `roof_selected_scenario = null`
- finite `xgboost_open_probability` in `[0,1]`
- finite `xgboost_closed_probability` in `[0,1]`
- finite `xgboost_scenario_delta` in `[-1,1]`
- a valid `roof_scenario_downstream` object

OPEN and CLOSED probabilities remain separate. They are never averaged and neither is selected before official roof resolution.

`roof_scenario_downstream` has exactly five fields: `status`, `agreement_status`, `open_state`, `closed_state`, and `shared_state`.

- Missing market/evaluator evidence: `status = NOT_EVALUATED_MISSING_EVIDENCE`, `agreement_status = NOT_EVALUABLE`, and all three state objects are null. No downstream decision is invented.
- OPEN/CLOSED agreement: `status = EVALUATED`, `agreement_status = AGREE`, and `open_state == closed_state == shared_state`. All three states are required and non-null.
- OPEN/CLOSED disagreement: `status = ROOF_SENSITIVE`, `agreement_status = ROOF_SENSITIVE`; `open_state` and `closed_state` are required and differ, while `shared_state = null`.

The JSON Schema fixes the allowed field shapes and nullability. Python runtime validation additionally enforces semantic object equality/inequality where JSON Schema cannot compare sibling object values.

### Resolved retractable-roof XGBoost state

When official roof state is known, XGBoost returns to ordinary `AVAILABLE` semantics with `support = SUPPORTED` and one concrete selected prediction. The resolved-roof V1 subshape preserves four roof provenance fields:

- `roof_resolution_status = OPEN | CLOSED`
- `roof_selected_scenario = open | closed`, matching the resolved status
- `xgboost_open_probability`
- `xgboost_closed_probability`

The concrete `prediction` must equal the selected frozen scenario probability. Pending-only `xgboost_scenario_delta` and `roof_scenario_downstream` fields are absent. Non-retractable ordinary outputs do not admit roof-only fields.

This contract representation does not alter frozen XGBoost features, candidate/configuration, categorical vocabulary, chronological fit/refit, or evaluator behavior.

## 7. Sleeper -> expected QB — `NFL_EDGE_EXPECTED_QB_RESOLVER_V1`

The existing `source_audits/sleeper_qb_v1` system remains the evidence source. This contract does not redesign that audit.

### Identity chain

The deterministic chain is:

`Sleeper player -> canonical NFL EDGE/nflverse QB -> model QB state`

The existing crosswalk priority remains authoritative: exact Sleeper ID first when present in the reference, then exact GSIS, exact ESPN, then provider-specific exact stable IDs. Name+team is only a flagged fallback requiring review. Ambiguous exact-ID collisions are terminal and must not silently fall through to a lower-priority match.

Production resolver rules:

- **Known identity:** resolve only when canonical identity and model-QB state are deterministic.
- **New player:** emit `NEW_PLAYER`; materialize/approve a canonical identity/model state before `RESOLVED` use.
- **Unresolved:** emit `UNRESOLVED`; no fuzzy silent match.
- **Duplicate/ambiguous:** emit `AMBIGUOUS`; human/official resolution required.
- **Missing Sleeper evidence:** emit `MISSING_EVIDENCE`; preserve missing-source warning/freshness.

### Starter changes

A changed expected starter is append/provenance behavior, never an overwrite:

1. preserve prior source/resolver snapshot
2. record a new source/resolver snapshot
3. emit a starter-change event referencing both provenance IDs
4. update current resolver state to the new snapshot
5. mark the affected game `rescore_required = true`
6. preserve `changed_at_utc`

The API only exposes a newly scored product after that rescore is complete and the complete product candidate passes validation.

### Source staleness

Sleeper's detailed source-audit state remains preserved as source warning/provenance (for example `FRESH_FETCH_CHANGED`, `STALE_LAST_SUCCESS`, `SCHEMA_DRIFT`). The product-facing resolver normalizes freshness to `FRESH | AGING | STALE | UNAVAILABLE` so clients do not infer status from timestamps.

### Manual/official override

Overrides are narrow audit records and require:

- game/team
- previous canonical QB value
- new canonical QB value
- reason
- evidence/source
- timestamp
- operator/provenance
- distinct old/new provenance IDs

An override produces `OVERRIDDEN`, a new immutable provenance record, and a rescore requirement. Silent edits are forbidden.

## 8. Live market — `NFL_EDGE_LIVE_MARKET_V1`

Observed V1 books: DraftKings, FanDuel, Pinnacle. Actionable retail V1 books: DraftKings and FanDuel only. Supported markets: Moneyline, Spread, Total.

Each offer is an exact tuple of canonical game, sportsbook, market, selection, line, price, snapshot time, provider, and normalized identity. `offer_id` is stable within a snapshot and must not duplicate another exact offer in the same book/market bucket.

### Missing/stale/duplicate behavior

- Missing book: omit it; never synthesize a fallback.
- Stale observation: retain only when policy chooses to expose it, but mark `freshness.state = STALE`; it cannot masquerade as current.
- Duplicate exact observation: reject the candidate snapshot rather than pick an arbitrary duplicate.
- Changed line or price: a new exact offer identity/observation.

### Retail and Pinnacle semantics

- **Best retail offer** means the best currently usable exact offer among observed DraftKings and FanDuel offers for the exact market/selection/line context being compared. It does not fabricate an absent book or convert a line.
- **Pinnacle** is the sharp benchmark/anchor when available under the frozen evaluator/selector architecture. It is not a football-model input, it is not a retail fallback, and it is not an actionable user exact-offer book in V1.

No Odds API acquisition is part of this contract freeze.

## 9. User persistence — `NFL_EDGE_USER_STATE_V1`

Minimum persistent VPS state:

- `schema_version`
- `user_id`
- `bankroll`
- `risk_profile`
- `created_at`
- `updated_at`

Risk profiles reference the already-frozen staking policy:

| Profile | Frozen unit % of bankroll |
|---|---:|
| Cautious | 0.50% |
| Conservative | 0.75% |
| Normal | 1.00% |
| Aggressive | 1.25% |
| Ultra | 1.50% |

The existing frozen staking implementation remains authoritative for the 2.5% per-wager cap, 10% slate cap, $0.50 minimum stake, and downward $0.50 rounding.

V1 bankroll constraint: finite USD decimal from $0.00 through $1,000,000,000.00 with at most two decimal places. `PUT /profile` validates then replaces the mutable bankroll/risk-profile fields and updates `updated_at`; `user_id`/`created_at` are stable.

**Invariant:** changing bankroll or risk profile cannot change football probabilities, evaluator verdict, selected headline lane, or `recommended_units`. It changes only dollar stake derived from the frozen unit recommendation.

No complex authentication system is defined here.

## 10. API surface

### `GET /api/v1/health`

Returns service status plus last successful publication time/version, current freshness, and last refresh failure metadata. It may be unhealthy/stale while the product endpoint continues serving the previous complete snapshot.

### `GET /api/v1/product/latest`

Returns one complete validated `NFL_EDGE_PRODUCT_API_V1` snapshot. Never returns a partially generated candidate.

### `GET /api/v1/games`

Returns the `games` board from the same latest snapshot plus product version/freshness envelope.

### `GET /api/v1/games/{game_id}`

Returns one game from that snapshot; unknown canonical ID is `404`.

### `POST /api/v1/evaluate-offer`

Accepts the exact-offer request above for DraftKings or FanDuel retail offers only. Evaluation uses already-generated football/model state plus the frozen evaluator/product-policy path. The request does not train a model and does not directly trigger scheduled football rescoring.

### `GET /api/v1/profile`

Returns `NFL_EDGE_USER_STATE_V1`.

### `PUT /api/v1/profile`

Validates bankroll/profile changes and persists them atomically. Response may add user-specific dollar stakes, but generic recommendation units remain unchanged.

### Error model

V1 errors use a stable envelope:

```json
{
  "error": {
    "code": "INVALID_REQUEST",
    "message": "human-readable non-secret summary",
    "request_id": "opaque-id",
    "details": {}
  }
}
```

Expected classes include `INVALID_REQUEST` (400), `NOT_FOUND` (404), `UNSUPPORTED_OFFER` (422 where appropriate), `STALE_PRODUCT`/`SERVICE_UNAVAILABLE` (503 where serving would be unsafe), and internal error (500). Error bodies and logs must not expose credentials/provider secrets.

## 11. Freshness contract

All client-relevant evidence uses the explicit normalized state:

- `FRESH`
- `AGING`
- `STALE`
- `UNAVAILABLE`

Each freshness object carries `observed_at_utc`, `age_seconds`, and `threshold_seconds`. `threshold_seconds` is the positive stale boundary chosen by the producer's operational policy. V1 derives the state deterministically from those fields:

- **FRESH:** `0 <= age_seconds < 0.5 * threshold_seconds`
- **AGING:** `0.5 * threshold_seconds <= age_seconds <= threshold_seconds`
- **STALE:** `age_seconds > threshold_seconds`
- **UNAVAILABLE:** no usable observation exists, so `observed_at_utc = null` and `age_seconds = null`

For `FRESH`, `AGING`, and `STALE`, `observed_at_utc` must be present and `age_seconds` must be finite and non-negative. `threshold_seconds` must always be finite and greater than zero. A payload whose declared state contradicts its age/threshold values is invalid. Therefore the browser uses the published state directly and never has to infer freshness semantics itself.

The actual threshold durations remain operational policy rather than model tuning and are not chosen from football outcomes by this contract. The mock fixture's threshold numbers are illustrative fixture values, not live production timer configuration.

## 12. Atomic publication and failure behavior

`src/nfl_edge/publication/live_product_v1.py` freezes the promotion sequence:

1. build the complete candidate in memory/work space
2. validate the entire `NFL_EDGE_PRODUCT_API_V1` contract
3. serialize JSON with `allow_nan=False`
4. write a uniquely named immutable timestamped snapshot
5. flush and `fsync` the file and directory
6. write/flush/fsync a temporary latest file
7. atomically `os.replace` it as `latest.json`
8. fsync the containing directory

If candidate validation, JSON serialization, or persistence fails, the prior valid `latest.json` remains untouched. Non-finite numeric values cannot be published. Refresh failure belongs in health/diagnostic metadata; a partial snapshot must never become current. Immutable snapshots and diagnostics preserve forensic evidence.

## 13. Security boundary

Private credentials are prohibited in:

- product JSON
- API response bodies
- frontend JavaScript/bundles
- logs
- committed fixtures

The browser never directly calls paid/private football or sportsbook providers. Provider credentials remain server-side/VPS-only. The API exposes normalized product state, not provider secrets.

## 14. Frozen architecture boundary

This contract references but does not alter:

- QB-Elo methodology
- XGBoost V2 model/features/parameters and validation-tail architecture
- Expected Margin
- Ridge Totals R4
- Moneyline / Spread V3 / Total evaluators
- confidence/trust layers
- Hit Rate / Balanced V2 / Value selectors
- recommended units and five risk profiles
- Play Through / Value At

2025 remains diagnostic evidence only. 2026 is prospective production. Any future implementation defect discovered while wiring these interfaces must be reported and handled explicitly; it is not permission to redesign the frozen architecture.