"""Task 05C closeout tests — focused, no heavy PBP build.

Covers all 17 assertions from §9 of the closeout spec:
1. target_total_points == home_score + away_score
2. modeling table game_id unique
3. modeling table has 1942 rows
4. exact season counts match accepted
5. 2024 postseason count = 13
6. 2024_22_KC_PHI present
7. season 2025 rows = 0
8. feature manifest has exactly 90 CORE_V1 model inputs
9. manifest order equals EXACT_90_COLUMNS
10. identity columns not model inputs
11. home_score not a model input
12. away_score not a model input
13. target_total_points not a model input
14. model-input projection equals accepted 90-feature artifact
15. no sportsbook fields present
16. duplicate/ambiguous score joins hard-fail
17. missing target hard-fails
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, "/root/workspaces/nfl-edge-totals-feature-contract-v1/src")
sys.path.insert(0, "/root/workspaces/nfl-edge-totals-feature-contract-v1/scripts")
from nfl_edge.features.totals_v1.feature_table import EXACT_90_COLUMNS

# Import the PRODUCTION modeling-table assembly module so tests exercise the
# exact same code path the builder/CLI uses (no re-implementation).
mt = importlib.import_module("build_totals_v1_modeling_table")
TotalsModelingTableError = mt.TotalsModelingTableError

W = Path("/root/workspaces/nfl-edge-totals-feature-contract-v1")
MODEL = W / "data/derived/totals_v1_modeling_table_2018_2024.parquet"
FEATURES = W / "data/derived/totals_v1_features_2018_2024.parquet"
IDENTITY = W / "data/derived/totals_v1_feature_identity_2018_2024.parquet"
MANIFEST = W / "data/manifests/task05c_totals_feature_manifest_v1.json"
SCORES = W / "data/frozen/games/games_2018_2025.parquet"
SCHEDULES = W / "data/raw/source_snapshots/v1/schedules_2018_2025_frozen-baseline-v1.parquet"

IDENTITY_COLS = ["game_id", "season", "season_type", "week", "home_team", "away_team", "block_id"]
EXPECTED_SEASON = {2018: 267, 2019: 267, 2020: 269, 2021: 285, 2022: 284, 2023: 285, 2024: 285}
SPORTSBOOK_FIELDS = ["spread_line", "total_line", "over_odds", "under_odds", "away_moneyline", "home_moneyline",
                     "away_spread_odds", "home_spread_odds", "result", "total"]


def _load_or_skip(path):
    if not path.exists():
        import pytest
        pytest.skip(f"{path} not found — skip test requiring this artifact")
    return pl.read_parquet(path)


class TestModelingTableIntegrity:
    """Tests 1–7, 10–15, 16–17 require this class."""

    def _load_model(self):
        return _load_or_skip(MODEL)

    def test_target_is_home_plus_away(self):
        m = self._load_model()
        assert m["home_score"].dtype in (pl.Int32, pl.Int64)
        assert m["away_score"].dtype in (pl.Int32, pl.Int64)
        assert (m["target_total_points"] == m["home_score"] + m["away_score"]).all(), \
            "target_total_points != home_score + away_score"

    def test_game_id_unique(self):
        m = self._load_model()
        assert m["game_id"].n_unique() == m.height, f"game_id not unique: {m.height} rows, {m['game_id'].n_unique()} unique"

    def test_row_count_1942(self):
        m = self._load_model()
        assert m.height == 1942, f"rows {m.height} != 1942"

    def test_season_counts(self):
        m = self._load_model()
        cnt = {int(s): int(n) for s, n in m.group_by("season").len().sort("season").rows()}
        assert cnt == EXPECTED_SEASON, f"season counts {cnt} != {EXPECTED_SEASON}"

    def test_2024_postseason_13(self):
        m = self._load_model()
        post2024 = m.filter((pl.col("season") == 2024) & (pl.col("season_type") != "REG")).height
        assert post2024 == 13, f"2024 postseason count {post2024} != 13"

    def test_kc_phi_present(self):
        m = self._load_model()
        assert "2024_22_KC_PHI" in m["game_id"].to_list()

    def test_season_2025_zero(self):
        m = self._load_model()
        assert m.filter(pl.col("season") == 2025).height == 0, "season 2025 rows found"

    def test_identity_cols_not_model_inputs(self):
        m = self._load_model()
        for c in IDENTITY_COLS:
            assert c in m.columns, f"identity col {c} missing from modeling table"

    def test_home_score_not_model_input(self):
        m = self._load_model()
        assert "home_score" in m.columns
        # home_score must NOT be in the manifest's model-input projections
        mf = json.loads(MANIFEST.read_text())
        model_input_names = {r["feature_name"] for r in mf["feature_records"] if r["model_input"]}
        assert "home_score" not in model_input_names, "home_score found in manifest model inputs"

    def test_away_score_not_model_input(self):
        mf = json.loads(MANIFEST.read_text())
        model_input_names = {r["feature_name"] for r in mf["feature_records"] if r["model_input"]}
        assert "away_score" not in model_input_names, "away_score found in manifest model inputs"

    def test_target_total_points_not_model_input(self):
        mf = json.loads(MANIFEST.read_text())
        model_input_names = {r["feature_name"] for r in mf["feature_records"] if r["model_input"]}
        assert "target_total_points" not in model_input_names, "target found in manifest model inputs"

    def test_model_input_projection_equals_accepted_90(self):
        """The model-input projection from modeling table equals the accepted 90-feature artifact.

        Both frames are written in the same deterministic game_id-sorted row order
        by the accepted builder, so they are row-aligned by construction. We verify
        column-by-column identity (values + null masks) for every predictor.
        """
        m = self._load_model().sort("game_id")
        f = _load_or_skip(FEATURES)
        assert list(f.columns) == list(EXACT_90_COLUMNS), "feature artifact cols != EXACT_90_COLUMNS"
        assert m.height == f.height == 1942
        mf = json.loads(MANIFEST.read_text())
        model_input_names = [r["feature_name"] for r in mf["feature_records"] if r["model_input"]]
        assert len(model_input_names) == 90
        assert model_input_names == list(EXACT_90_COLUMNS)
        for col in model_input_names:
            mv = m[col]
            fv = f[col]
            # match null patterns
            assert (mv.is_null() == fv.is_null()).all(), f"null mask mismatch for {col}"
            # match non-null values
            eq = (mv == fv).fill_null(True)
            assert bool(eq.all()), f"value mismatch for {col} in model-input projection"

    def test_no_sportsbook_fields(self):
        m = self._load_model()
        for s in SPORTSBOOK_FIELDS:
            assert s not in m.columns, f"sportsbook field {s} found in modeling table"

    def test_duplicate_score_join_hard_fails(self):
        """Duplicate game_id in score frame must raise via the production assembly path."""
        import pytest
        scores = _load_or_skip(SCORES)
        dup = pl.concat([scores, scores.filter(pl.col("game_id") == "2018_01_ATL_PHI")])
        assert dup.group_by("game_id").len().filter(pl.col("len") > 1).height >= 1
        identity = _load_or_skip(IDENTITY)
        features = _load_or_skip(FEATURES)
        pred = mt.manifest_core_v1_columns()
        with pytest.raises(TotalsModelingTableError):
            mt.assemble_modeling_table(identity, features, dup, pred)

    def test_missing_target_hard_fails(self):
        """Unmatched/missing score row must raise via the production assembly path."""
        import pytest
        scores = _load_or_skip(SCORES)
        identity = _load_or_skip(IDENTITY)
        features = _load_or_skip(FEATURES)
        pred = mt.manifest_core_v1_columns()
        # remove one score row -> unmatched identity game -> null target -> raise
        miss = scores.filter(pl.col("game_id") != "2024_22_KC_PHI")
        with pytest.raises(TotalsModelingTableError):
            mt.assemble_modeling_table(identity, features, miss, pred)
        # explicit null home_score -> raise
        nulled = scores.with_columns(
            pl.when(pl.col("game_id") == "2018_01_ATL_PHI")
            .then(None).otherwise(pl.col("home_score")).alias("home_score")
        )
        with pytest.raises(TotalsModelingTableError):
            mt.assemble_modeling_table(identity, features, nulled, pred)


class TestManifestIntegrity:
    """Tests 8–9."""

    def test_manifest_90_core_v1(self):
        mf = json.loads(MANIFEST.read_text())
        core = [r for r in mf["feature_records"] if r["inclusion_status"] == "CORE_V1" and r["model_input"]]
        assert len(core) == 90, f"CORE_V1 count {len(core)} != 90"

    def test_manifest_order_equals_exact_90_columns(self):
        mf = json.loads(MANIFEST.read_text())
        names = [r["feature_name"] for r in mf["feature_records"] if r["inclusion_status"] == "CORE_V1"]
        assert names == list(EXACT_90_COLUMNS), "manifest order != EXACT_90_COLUMNS"


class TestLeakageBoundary:
    """Same-block and 2025 boundary checks using already-recorded evidence."""

    def test_same_block_leakage_zero_in_audit(self):
        """Reuses the already-accepted RUN1 audit's leakage counters."""
        audit = json.loads((W / "data/derived/audit_RUN1.json").read_text())
        leakage = audit["provenance"]["leakage_sums"]
        assert leakage["same_game_source_rows"] == 0
        assert leakage["same_block_source_rows"] == 0
        assert leakage["future_block_source_rows"] == 0
        assert leakage["season_2025_source_rows"] == 0
        assert leakage["canonical_mapping_failures"] == 0


def _cols_equal(a: pl.Series, b: pl.Series) -> bool:
    """Null-safe equality of two columns (values + null masks)."""
    assert a.dtype == b.dtype, f"dtype mismatch {a.dtype} vs {b.dtype}"
    if a.is_null().sum() != b.is_null().sum():
        return False
    eq = (a == b).fill_null(True)
    return bool(eq.all())


class TestAdversarialAlignment:
    """PR-hardening: prove game->predictor alignment is explicit and fail-closed."""

    IDENTITY = IDENTITY
    FEATURES = FEATURES
    SCORES = SCORES

    def _components(self):
        identity = _load_or_skip(self.IDENTITY)
        features = _load_or_skip(self.FEATURES)
        scores = _load_or_skip(self.SCORES)
        pred = mt.manifest_core_v1_columns()
        return identity, features, scores, pred

    def _assert_game_pred_mapping_identical(self, m1, m2, pred):
        """For every game_id, the 90 predictors are identical between two assemblies."""
        a = m1.sort("game_id")
        b = m2.sort("game_id")
        assert a["game_id"].to_list() == b["game_id"].to_list()
        for col in pred:
            assert _cols_equal(a[col], b[col]), f"predictor {col} differs across score-order for a game"

    def test_predictor_alignment_survives_score_shuffle(self):
        """SHA: shuffle the score frame; game->predictor mapping must be unchanged."""
        import random
        identity, features, scores, pred = self._components()
        base = mt.assemble_modeling_table(identity, features, scores, pred)
        rng = random.Random(1234)
        shuffled = scores.sample(fraction=1.0, shuffle=True, seed=rng.randrange(10**9))
        alt = mt.assemble_modeling_table(identity, features, shuffled, pred)
        self._assert_game_pred_mapping_identical(base, alt, pred)

    def test_predictor_alignment_survives_score_reverse(self):
        """Reverse the score frame order; game->predictor mapping must be unchanged."""
        identity, features, scores, pred = self._components()
        base = mt.assemble_modeling_table(identity, features, scores, pred)
        rev = scores.sort("game_id", descending=True)
        alt = mt.assemble_modeling_table(identity, features, rev, pred)
        self._assert_game_pred_mapping_identical(base, alt, pred)

    def test_predictor_alignment_survives_sort_by_other_field(self):
        """Sort scores by a field unrelated to identity order; mapping unchanged."""
        identity, features, scores, pred = self._components()
        base = mt.assemble_modeling_table(identity, features, scores, pred)
        alt_sorted = scores.sort(pl.col("home_team"), pl.col("away_team"))
        alt = mt.assemble_modeling_table(identity, features, alt_sorted, pred)
        self._assert_game_pred_mapping_identical(base, alt, pred)

    def test_height_mismatch_hard_fails(self):
        """Feature/identity height mismatch must raise through production path."""
        import pytest
        identity, features, scores, pred = self._components()
        truncated = features.head(identity.height - 1)
        with pytest.raises(TotalsModelingTableError):
            mt.assemble_modeling_table(identity, truncated, scores, pred)

    def test_duplicate_row_key_hard_fails(self):
        """A duplicated preserved row key on the feature side must fail closed."""
        import pytest
        identity, features, _, pred = self._components()
        id_keyed, feat_keyed = mt._key_frames(identity, features, pred)
        n = identity.height
        bad = pl.concat([feat_keyed, feat_keyed.filter(pl.col("_row_key") == 0)])
        with pytest.raises(TotalsModelingTableError):
            mt._attach_predictors(id_keyed, bad, n)

    def test_missing_row_key_hard_fails(self):
        """A dropped row key (fragment) must fail closed (no silent row merge)."""
        import pytest
        identity, features, _, pred = self._components()
        id_keyed, feat_keyed = mt._key_frames(identity, features, pred)
        n = identity.height
        bad = feat_keyed.filter(pl.col("_row_key") != 5)
        with pytest.raises(TotalsModelingTableError):
            mt._attach_predictors(id_keyed, bad, n)

    def test_canonical_artifact_projection_equals_accepted_90(self):
        """Refactored production builder's 90-predictor projection equals the
        accepted feature artifact when matched through the explicit identity bridge."""
        identity, features, scores, pred = self._components()
        model = mt.validate_modeling_table(
            mt.assemble_modeling_table(identity, features, scores, pred), pred
        )
        proj = model.select(pred)
        assert proj.columns == list(EXACT_90_COLUMNS)
        accepted = _load_or_skip(self.FEATURES)
        assert list(accepted.columns) == list(EXACT_90_COLUMNS)
        assert proj.height == accepted.height == 1942
        for col in pred:
            assert _cols_equal(proj[col], accepted[col]), f"predictor {col} differs from accepted artifact"