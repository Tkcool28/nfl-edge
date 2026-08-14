# Task 05C — Phase 3E External Full-Data Validation Addendum

**IDENTIFIED AS:** External validation evidence. Did NOT run on this VPS.

**Pre-existing VPS Phase-3E report:** `reports/development/task05c_phase3e_validation.md`
(covers the team-normalization remediation VPS build with RUN1/RUN2 reproducibility
demonstrated on the same Hermes worker.)

## External test provenance

The validation bundle was exported from this VPS (where the PBP artifacts and
the prior Phase-3E build evidence live), its hashes/inventory were independently
verified, and the bundle was then uploaded into an **independent external
ChatGPT Work/cloud execution environment**. The dependencies used for the test
were installed in that cloud environment. The original VPS absolute PBP path was
unavailable there, so a temporary external test copy was made; the only
executable difference from the original test was the PBP root path.

Result archive (as present and verified on this VPS):
```
/tmp/task05c_phase3e_external_validation.zip
  byte_size:  117595520
  SHA-256:    07cdf5ee72b7b4ad6eb89857792e610893eba45acfdb84883f6bbbeb96cb1447
```

### Externally reported result

| Metric | Value |
|---|---|
| Temporary-wrapper executable equivalence | PASS |
| Only executable difference from original test | `pbp_root`: VPS absolute PBP root → bundled relative PBP root |
| Compilation | PASS |
| Pytest collection | PASS — one test collected |
| Executed target | `tests/features/_temporary_external_test_totals_v1_phase3d.py::TestRemediationFeatureIdentity::test_end_to_end_builder_returns_90_features` |
| Test result | PASS |
| Exit code | 0 |
| Elapsed | 152 seconds (pytest reported 150.98 s) |
| OOM/resource limit | none |

### What the passing test proved

The test's internal assertions demonstrated:

- `features.width == 90`
- `features.columns == EXACT_90_COLUMNS` (exact match)
- `identity.width == 7`
- `identity.columns == [game_id, season, season_type, week, home_team, away_team, block_id]`
- Feature/identity row alignment (identity rows == feature rows)
- No identity column leaked into features
- No feature column leaked into identity

### What the external test did NOT independently prove

The test did not independently print or assert the absolute row count (1942).

The 1942-row population remains separately proven by the existing full-build
reproducibility evidence (RUN1 feature fingerprint `db2461ff…` / identity
fingerprint `e98d1355…`, RUN1 == RUN2 == SHUFFLED, plus real-data audits).

### Relationship to accepted artifacts

The external test ran against the same feature builder code (`build_totals_v1_feature_table`)
using the same accepted frozen inputs. Its passing structural assertions are
consistent with the accepted artifacts:
- Feature artifact SHA-256: `d33d88cb97756e0074408ea4e859b6ae30e5ae7cfa428b3080799613c042a9f6`
- Identity artifact SHA-256: `67db18cd117fa2c789153d322807ae987159ea321e3c98ff56e077bbe1e8bf61`

### Note on missing zip scenario

The external validation zip was present at time of this addendum writing.
Its absence would NOT block closeout — the independently proven
RUN1==RUN2==SHUFFLED reproducibility (identical feature/identity fingerprints
and byte-identical parquet across three independent builds) and the real-data
audit at 1942 games remain the authoritative reproducibility evidence.