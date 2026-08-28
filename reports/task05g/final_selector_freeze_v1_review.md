# Task05G Final Selector Freeze V1 — Review

## Verdict

`FINAL_SELECTORS_V1_FROZEN_AND_INTEGRATED_REPLAY_MATCHES_ACCEPTED_DEVELOPMENT_EVIDENCE`

## Frozen semantic SHA

`f1611bd42475bf05c49188e07dfb494e5e1ce86e`

## Validated workflow

- workflow run: `33045100544`
- result: SUCCESS
- artifact: `9635344273`
- artifact digest: `sha256:e15021346f3062049c64e8e19c0c63da0ea41ab2df0a9af70d6dfed65779e95c`
- deterministic replay: PASS
- canonical selector tests: PASS
- frozen upstream focused tests: PASS
- Task05F board reproduction: PASS
- Model Confidence V2 reproduction: PASS
- Spread Confidence V3 reproduction: PASS
- 2025 firewall: PASS
- totals exclusion: PASS

## Overall selector replay, 2020–2024

- Hit Rate: 81/109 blocks, 53-27-1, 66.25% non-push hit, -2.75% flat ROI secondary.
- Balanced: 88/109 blocks, 54-34, 61.36% hit, -1.89% flat ROI secondary.
- Value: 68/109 blocks, 46-22, 67.65% hit, +43.20% flat ROI exposed-development only.

## Value stress year

2023 final Value is 7 plays, 3-4, -1.305u. The final safety policy reduced the previously exposed catastrophic drawdown while preserving a legitimately losing year rather than tuning it profitable.

## Defects encountered during integration

1. RED boundary test fixture used n=8 even though frozen RED threshold is strictly trust <.25; n=8 with zero data trust produces exactly .25. Test-only fixture corrected to n=9.
2. Initial canonical common filter accidentally added HIGH/MEDIUM reliability as an eligibility veto. This was not part of the accepted research protocol and caused major coverage mismatch. The veto was removed; Task05F `supported` + model-confidence support remain the common gate and reliability remains a tie-break/ranking field.

No 2025 data was used to identify or correct either defect.

## Canonical public Python interface

`src/nfl_edge/recommendation/__init__.py` now exports the canonical selectors from `final_selectors_v1.py`, while unit/risk/Play Through helpers continue to come from `policy.py` pending downstream Task05G reconciliation.

## Next bounded work

Do not alter selectors. Reconcile and validate the remaining Task05G scope:

- deterministic recommended units;
- five risk profiles;
- bankroll-to-dollar conversion, wager/slate caps, rounding, and overlap deduplication;
- Play Through exact-offer behavior;
- stored/manual offer parity;
- end-to-end 2020–2024 card/risk simulation;
- production output contract freeze required before opening 2025.

Full frontend/publication implementation is not part of this selector-freeze PR.
