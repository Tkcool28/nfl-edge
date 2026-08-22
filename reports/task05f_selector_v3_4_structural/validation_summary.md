# Task05F Selector V3.4 — No-Outcome Structural Evidence

Status: **VALID STRUCTURAL EXECUTION / COVERAGE RESTORED / PRICE-SUPPRESSION AUDIT REQUIRED**

This replay was preregistered in `config/task05f_selector_v3_4_structural_replay_v1.yaml`. It materialized the frozen 2020-2024 candidate table, attached Evaluated Wager Board V1 and Staking V2.1 fields, and ran the thin Selector V3.4. The historical outcome sidecar was never opened. No W/L/P, ROI, bankroll, or 2025 data entered this replay.

## Reproducibility

- Branch workflow commit: `cfb9e605d0167517090ce62eb74541db8b2adedc`
- GitHub Actions run: `32580689514`
- Artifact ID: `9477779830`
- Artifact ZIP digest: `sha256:def815418c745e21a69f5345bcc1a7b8cef5531d76efc38245cc529f91af5a46`
- GitHub Actions checked-out merge SHA recorded by runner: `202c1ab3b2ac80127f599a98ed1d5c34289c9619`
- `structural_summary.json` SHA-256: `6ed586b8dd5ce3a49c175a561f0f74834257cc1e1faed9ce8bda79963d315406`
- `selector_picks_no_outcomes.json` SHA-256: `fb695bf37816bf04ef59ea372383b11fa93928048e1a449dd7c3531255dec6b1`
- `provenance.json` SHA-256: `a9db7b24db4e5686beca64272a271f3cc0e55ed6ae26870a26d12aee42868579`
- Candidate rows: 8,448
- Evaluated-wager rows: 8,448
- Slates: 109
- Development seasons: 2020-2024
- Sealed 2025 loaded: **false**
- Historical outcomes scored: **false**
- Bankroll simulated: **false**
- Two structural runs deterministic: **PASS**

## Evaluator actionability

- Actionable evaluated wagers: **2,042 / 8,448**
- Nonactionable: **6,406**
- Actionable status mix: VALUE 1,683; PLAYABLE 359
- Actionable market mix: ML 865; spread 579; total 598
- Actionable reliability mix: HIGH 11; MEDIUM 605; LOW 1,426
- LOW-reliability actionable rows: **1,426**

This confirms Staking V2.1 removed the previous LOW-reliability hard veto. LOW remains a risk/reliability label but no longer automatically erases an evaluator-approved VALUE/PLAYABLE wager.

## Featured-card structural coverage

| Card | Plays | No-play | ML | Spread | Total |
|---|---:|---:|---:|---:|---:|
| High Hit Rate | 90 | 19 | 17 | 53 | 20 |
| Balanced | 93 | 16 | 24 | 20 | 49 |
| Value | 98 | 11 | 48 | 13 | 37 |

Slates by number of distinct featured cards:

- 0 cards: 10
- 1 card: 5
- 2 cards: 6
- 3 cards: **88**

No market quota or market-specific primary-card eligibility produced these mixes. Market type is metadata to Selector V3.4.

## Card composition

### High Hit Rate

- Mean model-native cash-confidence proxy: **0.7352**
- Range: **0.5246 to 0.9040**
- Mean evaluator units: **1.0369u**
- Status: 69 VALUE / 21 PLAYABLE
- Reliability: 1 HIGH / 39 MEDIUM / 50 LOW

### Balanced

- Mean model-native cash-confidence proxy: **0.6030**
- Range: **0.4205 to 0.8239**
- Mean evaluator units: **1.1423u**
- Status: 92 VALUE / 1 PLAYABLE
- Reliability: 10 MEDIUM / 83 LOW

### Value

- Mean model-native cash-confidence proxy: **0.4745**
- Range: **0.1130 to 0.8665**
- Mean evaluator units: **1.1640u**
- Status: 98 VALUE
- Reliability: 11 MEDIUM / 87 LOW

The Value card is allowed to have a low football-confidence proxy because its product question is strict positive EV, not highest cash probability. Balanced and HHR use their separate objectives.

## Remaining suppression diagnostic

Every one of the 109 slates had at least one finite model-native cash-confidence proxy above 0.50. The single highest-football-confidence wager on each slate was:

- evaluator-actionable: **31**
- blocked: **78**

Blocked reasons:

- LEAN / `STATUS_NOT_ACTIONABLE`: **65**
- PASS / `UNSUPPORTED`: **13**

Blocked reliability labels:

- LOW: 35
- MEDIUM: 30
- UNSUPPORTED: 13

This shows the earlier reliability hard veto is no longer the main suppression mechanism. The remaining question is **price/Play Through actionability**: whether the 65 supported LEAN top-confidence wagers are just beyond the accepted Play Through corridor or are materially overpriced. That must be measured structurally, without outcomes or threshold tuning, before freezing HHR actionability.

## Decision

- Evaluated Wager Board V1 responsibility split: **structurally supported**.
- Staking V2.1 removal of LOW hard veto: **structurally supported**.
- Thin Selector V3.4 market-agnostic selection: **structurally supported**.
- Coverage problem from V3.1: **materially improved**.
- Final HHR/Play Through actionability freeze: **deferred pending no-outcome price-suppression audit**.
- 2025 remains sealed.
