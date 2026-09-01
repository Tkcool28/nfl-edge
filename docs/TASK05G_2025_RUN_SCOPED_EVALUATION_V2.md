# Task05G run-scoped 2025 evaluation v2

`task05g_2025_evaluation_v2.py` is an additive wrapper around the frozen
Task05G runtime. It does **not** replace or invoke the legacy v1 one-spend gate
or script, and it never uses the legacy acceptance configuration as a v2
execution gate. Before v2 authorization can proceed, it runs the existing
read-only frozen-contract audit; that audit validates pre-2025/frozen
methodology identities without opening 2025 inputs.

## Execution contract

```bash
python scripts/task05g_2025_evaluation_v2.py --preflight
python scripts/task05g_2025_evaluation_v2.py \
  --run-id operator-approved-id \
  --authorization "$NFL_EDGE_2025_AUTHORIZATION" \
  --market-root "$NFL_EDGE_2025_MARKET_ROOT"
```

`--run-id` is limited to safe ASCII letters/digits plus `.`, `_`, and `-`, with
at most 80 characters. A run reserves exactly:

`artifacts/task05g_2025_holdout_v2/<run-id>/`

An already-existing run directory is a closed failure. No output is removed,
reused, or overwritten. Distinct safe IDs have distinct output roots.

After authorization and development-only bootstrap, `RUN_STARTED.json` is
created with exclusive creation before the runtime receives any 2025 input.
`RUN_TERMINAL.json` is the single exclusive terminal claim. Success also creates
an immutable `RUN_COMPLETED.json` view; a runtime exception creates an immutable
`RUN_FAILED.json` view. A second terminal outcome cannot be recorded.

## Provenance and historical v1 boundary

`RUN_STARTED.json` records UTC start time, branch/HEAD/tracked cleanliness,
script/runtime/config identities, Python/platform metadata, Task05F board SHA,
Oracle identity, Task05C PBP and observation identities from frozen metadata,
and canonical 2025 market identities. It records the legacy v1 spend marker only
as a presence boolean. It is never read as a blocking gate and is never changed.

The composed runtime retains its existing freeze-before-reveal, model,
evaluator, selector, staking, product, and sealed-development behavior. This
wrapper adds no model-methodology or acquisition behavior.
