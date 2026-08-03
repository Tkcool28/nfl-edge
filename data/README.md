# Data Area

This directory holds auditable project evidence, not disposable local caches.

```text
manifests/  source identity, retrieval metadata, schemas, row counts, checksums
frozen/     compact immutable historical tables approved for modeling
fixtures/   tiny deterministic datasets used by tests
```

Large raw source archives belong in GitHub Release assets when normal Git history would become cumbersome. Local raw downloads use `data/raw/` and are ignored.

No frozen file may be replaced under the same version. See `docs/data_contract.md`.
