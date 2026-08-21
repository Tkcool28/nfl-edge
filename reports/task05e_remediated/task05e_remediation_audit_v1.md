# Task 05E pass-2 remediation audit (before vs after)

- prereg fingerprint: `d195340940e5c9d6c9f62bbfbb8f8f50836013e05334e870f0905d3592d62e5c`
- candidate lock SHA: `41c909823a58e9fb5d7de6a4be8c4de55537974d61ddaedffd12acd8c119ead0`
- BEFORE = frozen D4/D5 artifacts (invalid implementation)
- AFTER  = pass-2 repo-native scorer ledgers

## Spread shopping effect (same rows, stale price-first census vs reconstructed number-first)

| period | union N (after) | changed line vs census | changed price vs census |
|---|---|---|---|
| DISCOVERY | 460 | 150 | 141 |
| CONFIRMATION | 340 | 120 | 115 |

## Locked candidates (BEFORE vs AFTER), N / ROI

| candidate | DISCOVERY before (N,ROI) | DISCOVERY after (N,ROI) | CONF before (N,ROI) | CONF after (N,ROI) | ML changed? |
|---|---|---|---|---|---|
| ML_DOG_VALUE_ZONE_AVG | (149,0.2520) | (131,0.2684) | (112,-0.2372) | (101,-0.2309) | True |
| ML_CORROBORATED_DOG_VALUE_ZONE | (85,0.2807) | (85,0.2807) | (55,-0.3185) | (55,-0.3185) | False |
| ML_AVG_0_2 | (136,0.1544) | (126,0.1373) | (104,-0.1464) | (90,-0.2814) | True |
| SPREAD_0_4_DISCOVERY_UNION | (467,0.3946) | (460,0.1002) | (342,-0.0136) | (340,-0.0052) | False |

## Notes

- ML candidates: pass-2 did not retune or re-shop ML; ML rows are IDENTICAL to pass-1 so any drift from D4/D5 reflects pass-1 AVG/bucket corrections only (flagged if present).
- SPREAD: reconstructed number-first shopping (shop_spread) replaces the stale price-first census act_line/act_price; ROI/line/price shift as tabulated.
- 2025 remains sealed and unopened (HARD_REJECT before any filtering).
