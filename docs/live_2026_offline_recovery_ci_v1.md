# Live 2026 offline recovery CI

The recovery PR workflow runs at the exact contributor head SHA on Ubuntu 24.04 with Python 3.11, the accepted Market Product NumPy/SciPy/scikit-learn versions, and the existing single-thread BLAS settings. It publishes a compatibility JUnit report and a deterministic historical replay manifest. The existing Market Product fixture gate independently checks exact regeneration of the frozen entering state. Ordinary PRs keep the existing football compatibility tests. Live Sleeper and nflverse diagnostics require a manual run. The older Week 2 job that combined actual settlement with invented QB rows has been removed.

The historical job replays the previously reviewed Week 7 pre-provider boundary at `2026-10-21T13:26:33Z`. Its settled manifest and expected coverage come from `reports/historical_surface_recovery_week7_v1/`. It uses the canonical pre-provider command twice in fresh evidence directories. It checks both runs for exact agreement and checks game counts, completed state blocks, Sleeper snapshot identity, and selector observation counts against the reviewed baseline. It records the computed football snapshot hash and state version. Those two outputs can depend on the numerical runtime and are compared between runs.

## Supply the reviewed evidence

A maintainer must package the preserved files from the original Week 7 recovery. The review reports and the Weeks 2–5 selector archive alone are insufficient. Use original Weeks 2–6 selector snapshots and successful run statuses, the original Week 7-input Sleeper snapshot and normalized evidence, and the original settled evidence and schedule checkpoints.

Build a gzip-compressed tar of regular file entries with these relative paths. Supply a file list to tar to omit directory headers.

- `weekly/settled_evidence_manifest.json`, the four `weekly/settled_*.parquet`, `weekly/week{1..7}_schedule_v1.json`, and the referenced `weekly/schedule_checkpoints/<sha256>.json`
- `sleeper/latest_snapshot.json`, `sleeper/latest_run_status.json`, and `sleeper/normalized/qb_{snapshots,identity_crosswalk,evidence_states,change_ledger}.parquet` (the change ledger is optional if the original source omitted it)
- `native/<original-run-id>/run-status.json` and `native/<original-run-id>/product/deterministic-proof.json`

Verify the file bytes and provenance against the original archive, the Week 6 transfer hashes, and the Week 7 recovery records before approving the archive digest. Keep the archive in an access-controlled object store with a read-only, direct HTTPS download URL. Set the GitHub Actions repository secret `NFL_EDGE_RECOVERY_ARCHIVE_URL` to this URL and the repository variable `NFL_EDGE_RECOVERY_ARCHIVE_SHA256` to the independently verified SHA-256. Refresh the URL when it expires. Keep secret access limited to trusted same-repository workflow authors. Fork PRs run the compatibility job only. A missing secret or digest fails the historical job on same-repository PRs.

Checkout, dependency setup, evidence transport, and artifact upload use GitHub runner networking. Offline tests and canonical replay run in a new Linux network namespace with a clean environment and dropped privileges. The archive transport URL is available only to the staging step. The public workflow outputs contain test results, hashes, counts, and the canonical verdict. The archive, market rows, QB tables, and raw replay output are excluded from uploads.

Stage A establishes the CI gate against the historical Week 7 baseline. Week 9 reconstruction and Week 10 qualification require their own authentic evidence and review.
