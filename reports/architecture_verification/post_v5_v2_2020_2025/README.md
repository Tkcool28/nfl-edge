# Post-V5 V2 Architecture Verification Evidence

This directory permanently preserves the two diagnostic ZIP artifacts used to verify the merged post-V5 V2 architecture across historical seasons and exposed 2025.

## Authority

- Production architecture merge commit: `91e7362aca589179ab4c8f92009315a26bb45faf`
- Diagnostic harness PR: `#94` — closed unmerged after verification
- No new Odds API calls were made for this verification.
- No thresholds, model parameters, selector bounds, or staking rules were retuned from these results.
- 2025 is exposed diagnostic evidence only and must never be treated as a fresh holdout.

## Artifacts

- `post-v5-v2-historical-e2e.zip` — canonical historical XGBoost V1 reproduction control, V2 adaptive regeneration, and downstream Task05F/confidence/selector propagation.
- `post-v5-v2-all-years-diagnostic.zip` — all-years architecture diagnostic including 2020-2024 replay, XGBoost V2 availability evidence, and true 2025 V2 chronology.

`MANIFEST.json` records GitHub workflow run IDs, artifact IDs, source head SHA, exact repository ZIP SHA-256 values, and byte sizes.

These files are the evidence of record. Future architecture discussions should inspect these artifacts and manifest rather than rely on conversational memory.
