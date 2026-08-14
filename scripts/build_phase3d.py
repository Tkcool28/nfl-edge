#!/usr/bin/env python3
"""Real-data development build for Phase 3D (remediated).

Assertions:
- result.features contains exactly the 90 declared feature columns
- result.identity contains exactly the 7 identity columns
- features and identity are row-aligned
"""
import sys
sys.path.insert(0, '/root/workspaces/nfl-edge-totals-feature-contract-v1/src')

import hashlib
import polars as pl
from pathlib import Path
from nfl_edge.features.totals_v1.feature_table import build_totals_v1_feature_table, EXACT_90_COLUMNS

IDENTITY_COLUMNS = ["game_id", "season", "season_type", "week", "home_team", "away_team", "block_id"]

pbp_root = Path('/var/lib/chatgpt-vps-mcp/artifacts/nfl-edge/raw/task05c_pbp_v1')
oracle_qb_path = Path('data/derived/oracle_qb_entering_state_v2/oracle_qb_entering_state_game_sides_2018_2024_v2.parquet')
schedule = pl.read_parquet('data/raw/source_snapshots/v1/schedules_2018_2025_frozen-baseline-v1.parquet')
canonical_games = pl.read_parquet('data/frozen/games/games_2018_2025.parquet')

print('Building feature table...')
result = build_totals_v1_feature_table(pbp_root, schedule, canonical_games, oracle_qb_path)

ft = result.features
identity = result.identity
prov = result.provenance

# === Mandatory assertions ===
assert ft.width == 90, f"FAIL: features width {ft.width} != 90"
assert ft.columns == list(EXACT_90_COLUMNS), "FAIL: feature columns do not match EXACT_90_COLUMNS"
assert identity.width == 7, f"FAIL: identity width {identity.width} != 7"
assert identity.columns == IDENTITY_COLUMNS, f"FAIL: identity columns mismatch: {identity.columns}"
assert identity.height == ft.height, f"FAIL: identity rows {identity.height} != feature rows {ft.height}"

# No identity column in features
for col in IDENTITY_COLUMNS:
    assert col not in ft.columns, f"FAIL: identity column {col!r} leaked into features"

# No feature column in identity
for col in EXACT_90_COLUMNS:
    assert col not in identity.columns, f"FAIL: feature column {col!r} leaked into identity"

print(f'Feature rows: {ft.height}')
print(f'Feature width: {ft.width} (== 90)')
print(f'Identity rows: {identity.height}')
print(f'Identity width: {identity.width} (== 7)')
print(f'Provenance records: {len(prov)}')

# Season counts (from identity, not features)
print('\n--- Season counts ---')
seasons = identity['season'].unique().sort().to_list()
total_rows = 0
for s in seasons:
    sub = identity.filter(pl.col('season') == s)
    reg = sub.filter(pl.col('season_type') == 'REG')
    post = sub.filter(pl.col('season_type') != 'REG')
    print(f'  Season {s}: {sub.height} games ({reg.height} REG, {post.height} POST)')
    total_rows += sub.height
print(f'Total: {total_rows}')

# Calendar-2025 games (from identity)
post_2024 = identity.filter((pl.col('season') == 2024) & (pl.col('season_type') != 'REG'))
print(f'\n2024 postseason games (calendar 2025): {post_2024.height}')
print(f'2024_22_KC_PHI present: {"2024_22_KC_PHI" in identity["game_id"].to_list()}')

# Season 2025 check (from identity)
s2025 = identity.filter(pl.col('season') == 2025)
print(f'Season 2025 rows: {s2025.height}')

# Null/missing counts by feature family
print('\n--- Null/missing counts by feature family ---')
for col in EXACT_90_COLUMNS:
    null_count = ft[col].null_count()
    if null_count > 0 or col.endswith('_missing'):
        missing_sum = ft[col].sum() if col.endswith('_missing') else None
        extra = f', missing_sum={int(missing_sum)}' if missing_sum is not None else ''
        print(f'  {col}: nulls={null_count}{extra}')

# Provenance
print(f'\n--- Provenance ---')
print(f'Number of provenance records: {len(prov)}')
if prov:
    total_same_game = sum(p.same_game_source_rows for p in prov)
    total_same_block = sum(p.same_block_source_rows for p in prov)
    total_future = sum(p.future_block_source_rows for p in prov)
    total_s2025 = sum(p.season_2025_source_rows for p in prov)
    total_mapping = sum(p.canonical_mapping_failures for p in prov)
    total_fallback = sum(p.dropback_fallback_rows for p in prov)
    print(f'same_game_source_rows: {total_same_game}')
    print(f'same_block_source_rows: {total_same_block}')
    print(f'future_block_source_rows: {total_future}')
    print(f'season_2025_source_rows: {total_s2025}')
    print(f'canonical_mapping_failures: {total_mapping}')
    print(f'dropback_fallback_rows: {total_fallback}')

# Reproducibility fingerprint (exact 90-column feature matrix only)
# Sort by game_id for deterministic ordering using identity for alignment
identity_sorted = identity.sort("game_id")
# Use the same row ordering on features via row_index join
ft_indexed = ft.with_row_index("_sort_idx")
# Keep ALL identity columns plus the index so the sidecar carries the full
# seven-field identity aligned with features after sorting.
id_indexed = identity.with_row_index("_sort_idx")
sort_map = id_indexed.sort("game_id").with_row_index("_final_order")
ft_sorted = (
    ft_indexed
    .join(sort_map.select("_sort_idx", "_final_order"), on="_sort_idx", how="left")
    .sort("_final_order")
    .drop("_sort_idx", "_final_order")
)
identity_sorted_final = (
    id_indexed
    .join(sort_map.select("_sort_idx", "_final_order"), on="_sort_idx", how="left")
    .sort("_final_order")
    .drop("_sort_idx", "_final_order")
)
# The persisted identity sidecar must contain exactly the 7 identity fields.
id_sorted_clean = identity_sorted_final.select(IDENTITY_COLUMNS)
serialized = ft_sorted.serialize()
fp = hashlib.sha256(serialized).hexdigest()
print(f'\nExact-90 feature fingerprint (SHA-256): {fp}')

# Persist artifacts
feat_path = Path('data/derived/totals_v1_features_2018_2024.parquet')
id_path = Path('data/derived/totals_v1_feature_identity_2018_2024.parquet')
ft_sorted.write_parquet(feat_path)
id_sorted_clean.write_parquet(id_path)

feat_sha = hashlib.sha256(feat_path.read_bytes()).hexdigest()
id_sha = hashlib.sha256(id_path.read_bytes()).hexdigest()
print(f'\nFeature artifact: {feat_path} (SHA-256: {feat_sha})')
print(f'Identity artifact: {id_path} (SHA-256: {id_sha})')

print('\n=== ALL ASSERTIONS PASSED ===')
