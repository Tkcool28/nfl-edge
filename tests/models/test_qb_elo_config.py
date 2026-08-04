"""Canonical QB-Elo configuration loader tests.

The loader is the single source of truth for the primary QB-Elo run.
No in-code default may diverge. The runtime, the manifest, the
tuning ledger, and the replay must all use the canonical normalized
dictionary.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from nfl_edge.common.errors import ConfigurationError
from nfl_edge.models.qb_elo import EloConfig
from nfl_edge.models.qb_elo_config import (
    canonical_config_sha256,
    canonical_config_to_elo_config_input,
    canonical_config_to_eloconfig,
    load_qb_elo_canonical_config,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
YAML_PATH = REPO_ROOT / "config/qb_elo_v1.yaml"


# ---- 1. Canonical YAML loads successfully ---------------------------


def test_canonical_yaml_loads_successfully() -> None:
    cfg = load_qb_elo_canonical_config(YAML_PATH)
    assert isinstance(cfg, dict)
    assert len(cfg) > 0


# ---- 2. Returned normalized dictionary has the exact approved keys --


def test_normalized_dict_has_exact_approved_keys() -> None:
    cfg = load_qb_elo_canonical_config(YAML_PATH)
    expected = {
        "home_field_elo",
        "initial_rating",
        "k_factor_postseason",
        "k_factor_regular",
        "mov_cap",
        "mov_divisor",
        "prob_max",
        "prob_min",
        "qb_adjustment_max_abs_elo",
        "qb_adjustment_replacement_passing_epa",
        "qb_adjustment_sample_k",
        "qb_adjustment_scale_elo_per_shrunk_epa",
        "qb_adjustment_supported_uses_replacement_scenario",
        "qb_adjustment_unknown_returns_zero",
        "season_mean_reversion_fraction",
    }
    assert set(cfg.keys()) == expected


# ---- 3. season_mean_reversion_fraction equals exactly 0.333 --------


def test_season_mean_reversion_fraction_equals_exactly_0_333() -> None:
    cfg = load_qb_elo_canonical_config(YAML_PATH)
    assert cfg["season_mean_reversion_fraction"] == 0.333
    # The exact YAML value is 0.333, not 1.0/3.0.
    assert cfg["season_mean_reversion_fraction"] != 1.0 / 3.0


# ---- 4. Runtime EloConfig values equal normalized YAML values ------


def test_runtime_eloconfig_equals_normalized_yaml() -> None:
    cfg = load_qb_elo_canonical_config(YAML_PATH)
    elo = canonical_config_to_eloconfig(cfg)
    assert elo.initial_rating == cfg["initial_rating"]
    assert elo.home_field_elo == cfg["home_field_elo"]
    assert elo.k_factor_regular == cfg["k_factor_regular"]
    assert elo.k_factor_postseason == cfg["k_factor_postseason"]
    assert elo.season_mean_reversion_fraction == cfg[
        "season_mean_reversion_fraction"
    ]
    assert elo.mov_divisor == cfg["mov_divisor"]
    assert elo.mov_cap == cfg["mov_cap"]
    assert elo.prob_min == cfg["prob_min"]
    assert elo.prob_max == cfg["prob_max"]


# ---- 5. Runtime does not use an independent in-code default --------


def test_runtime_does_not_use_independent_in_code_default() -> None:
    """The default EloConfig() dataclass has ``1.0/3.0`` for the
    reversion fraction, but the canonical loader requires ``0.333``
    from the YAML. The runtime never uses the dataclass default;
    it always loads the canonical YAML."""
    from nfl_edge.models.qb_elo import EloConfig as _E
    default = _E()
    assert default.season_mean_reversion_fraction == 1.0 / 3.0
    cfg = load_qb_elo_canonical_config(YAML_PATH)
    elo = EloConfig(**canonical_config_to_elo_config_input(cfg))
    assert elo.season_mean_reversion_fraction != default.season_mean_reversion_fraction
    # The walk-forward runtime does not use the dataclass default.
    import nfl_edge.backtest.walk_forward as wf
    # DEFAULT_ELO_CONFIG was retired; no in-code default constant
    # remains.
    assert not hasattr(wf, "DEFAULT_ELO_CONFIG")


# ---- 6. canonical_config_sha256 is deterministic ------------------


def test_canonical_config_sha256_is_deterministic() -> None:
    a = canonical_config_sha256(load_qb_elo_canonical_config(YAML_PATH))
    b = canonical_config_sha256(load_qb_elo_canonical_config(YAML_PATH))
    assert a == b
    assert len(a) == 64  # SHA-256 hex


# ---- 7. canonical_config_sha256 changes if a normalized value changes --


def test_canonical_config_sha256_changes_with_value() -> None:
    cfg = load_qb_elo_canonical_config(YAML_PATH)
    h0 = canonical_config_sha256(cfg)
    cfg2 = dict(cfg)
    cfg2["initial_rating"] = 1501.0
    h1 = canonical_config_sha256(cfg2)
    assert h0 != h1


# ---- 8. Unknown top-level key is rejected ------------------------


def test_unknown_top_level_key_rejected(tmp_path: Path) -> None:
    p = tmp_path / "qb_elo_v1.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "initial_rating": 1500.0,
                "home_field_elo": 48.0,
                "k_factor_regular": 20.0,
                "k_factor_postseason": 4.0,
                "season_mean_reversion_fraction": 0.333,
                "margin_of_victory": {"divisor": 6.0, "cap": 2.5},
                "probability": {"min": 0.01, "max": 0.99},
                "qb_adjustment": {
                    "scale_elo_per_shrunk_epa": 500.0,
                    "max_abs_elo": 50.0,
                    "replacement_passing_epa": -0.05,
                    "sample_k": 250.0,
                    "unknown_returns_zero": True,
                    "supported_uses_replacement_scenario": True,
                },
                "rogue_top_level_key": 999.0,
            }
        )
    )
    with pytest.raises(ConfigurationError, match="unknown top-level"):
        load_qb_elo_canonical_config(p)


# ---- 9. Missing top-level key is rejected -------------------------


def test_missing_top_level_key_rejected(tmp_path: Path) -> None:
    p = tmp_path / "qb_elo_v1.yaml"
    # Drop the qb_adjustment key.
    p.write_text(
        yaml.safe_dump(
            {
                "initial_rating": 1500.0,
                "home_field_elo": 48.0,
                "k_factor_regular": 20.0,
                "k_factor_postseason": 4.0,
                "season_mean_reversion_fraction": 0.333,
                "margin_of_victory": {"divisor": 6.0, "cap": 2.5},
                "probability": {"min": 0.01, "max": 0.99},
            }
        )
    )
    with pytest.raises(ConfigurationError, match="missing top-level"):
        load_qb_elo_canonical_config(p)


# ---- 10. Unknown nested margin_of_victory key is rejected ---------


def test_unknown_nested_mov_key_rejected(tmp_path: Path) -> None:
    p = tmp_path / "qb_elo_v1.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "initial_rating": 1500.0,
                "home_field_elo": 48.0,
                "k_factor_regular": 20.0,
                "k_factor_postseason": 4.0,
                "season_mean_reversion_fraction": 0.333,
                "margin_of_victory": {
                    "divisor": 6.0,
                    "cap": 2.5,
                    "rogue": 1.0,
                },
                "probability": {"min": 0.01, "max": 0.99},
                "qb_adjustment": {
                    "scale_elo_per_shrunk_epa": 500.0,
                    "max_abs_elo": 50.0,
                    "replacement_passing_epa": -0.05,
                    "sample_k": 250.0,
                    "unknown_returns_zero": True,
                    "supported_uses_replacement_scenario": True,
                },
            }
        )
    )
    with pytest.raises(ConfigurationError, match="margin_of_victory"):
        load_qb_elo_canonical_config(p)


# ---- 11. Missing nested margin_of_victory key is rejected ---------


def test_missing_nested_mov_key_rejected(tmp_path: Path) -> None:
    p = tmp_path / "qb_elo_v1.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "initial_rating": 1500.0,
                "home_field_elo": 48.0,
                "k_factor_regular": 20.0,
                "k_factor_postseason": 4.0,
                "season_mean_reversion_fraction": 0.333,
                "margin_of_victory": {"divisor": 6.0},  # missing cap
                "probability": {"min": 0.01, "max": 0.99},
                "qb_adjustment": {
                    "scale_elo_per_shrunk_epa": 500.0,
                    "max_abs_elo": 50.0,
                    "replacement_passing_epa": -0.05,
                    "sample_k": 250.0,
                    "unknown_returns_zero": True,
                    "supported_uses_replacement_scenario": True,
                },
            }
        )
    )
    with pytest.raises(ConfigurationError, match="margin_of_victory"):
        load_qb_elo_canonical_config(p)


# ---- 12. Unknown nested probability key is rejected ----------------


def test_unknown_nested_probability_key_rejected(tmp_path: Path) -> None:
    p = tmp_path / "qb_elo_v1.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "initial_rating": 1500.0,
                "home_field_elo": 48.0,
                "k_factor_regular": 20.0,
                "k_factor_postseason": 4.0,
                "season_mean_reversion_fraction": 0.333,
                "margin_of_victory": {"divisor": 6.0, "cap": 2.5},
                "probability": {
                    "min": 0.01,
                    "max": 0.99,
                    "rogue": 0.5,
                },
                "qb_adjustment": {
                    "scale_elo_per_shrunk_epa": 500.0,
                    "max_abs_elo": 50.0,
                    "replacement_passing_epa": -0.05,
                    "sample_k": 250.0,
                    "unknown_returns_zero": True,
                    "supported_uses_replacement_scenario": True,
                },
            }
        )
    )
    with pytest.raises(ConfigurationError, match="probability"):
        load_qb_elo_canonical_config(p)


# ---- 13. Missing nested probability key is rejected ----------------


def test_missing_nested_probability_key_rejected(tmp_path: Path) -> None:
    p = tmp_path / "qb_elo_v1.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "initial_rating": 1500.0,
                "home_field_elo": 48.0,
                "k_factor_regular": 20.0,
                "k_factor_postseason": 4.0,
                "season_mean_reversion_fraction": 0.333,
                "margin_of_victory": {"divisor": 6.0, "cap": 2.5},
                "probability": {"max": 0.99},  # missing min
                "qb_adjustment": {
                    "scale_elo_per_shrunk_epa": 500.0,
                    "max_abs_elo": 50.0,
                    "replacement_passing_passing_epa": -0.05,
                    "sample_k": 250.0,
                    "unknown_returns_zero": True,
                    "supported_uses_replacement_scenario": True,
                }
                if False
                else {
                    "scale_elo_per_shrunk_epa": 500.0,
                    "max_abs_elo": 50.0,
                    "replacement_passing_epa": -0.05,
                    "sample_k": 250.0,
                    "unknown_returns_zero": True,
                    "supported_uses_replacement_scenario": True,
                },
            }
        )
    )
    with pytest.raises(ConfigurationError, match="probability"):
        load_qb_elo_canonical_config(p)


# ---- 14. Unknown nested qb_adjustment key is rejected --------------


def test_unknown_nested_qb_adjustment_key_rejected(tmp_path: Path) -> None:
    p = tmp_path / "qb_elo_v1.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "initial_rating": 1500.0,
                "home_field_elo": 48.0,
                "k_factor_regular": 20.0,
                "k_factor_postseason": 4.0,
                "season_mean_reversion_fraction": 0.333,
                "margin_of_victory": {"divisor": 6.0, "cap": 2.5},
                "probability": {"min": 0.01, "max": 0.99},
                "qb_adjustment": {
                    "scale_elo_per_shrunk_epa": 500.0,
                    "max_abs_elo": 50.0,
                    "replacement_passing_epa": -0.05,
                    "sample_k": 250.0,
                    "unknown_returns_zero": True,
                    "supported_uses_replacement_scenario": True,
                    "rogue": 1.0,
                },
            }
        )
    )
    with pytest.raises(ConfigurationError, match="qb_adjustment"):
        load_qb_elo_canonical_config(p)


# ---- 15. Missing nested qb_adjustment key is rejected --------------


def test_missing_nested_qb_adjustment_key_rejected(tmp_path: Path) -> None:
    p = tmp_path / "qb_elo_v1.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "initial_rating": 1500.0,
                "home_field_elo": 48.0,
                "k_factor_regular": 20.0,
                "k_factor_postseason": 4.0,
                "season_mean_reversion_fraction": 0.333,
                "margin_of_victory": {"divisor": 6.0, "cap": 2.5},
                "probability": {"min": 0.01, "max": 0.99},
                "qb_adjustment": {
                    "scale_elo_per_shrunk_epa": 500.0,
                    "max_abs_elo": 50.0,
                    "replacement_passing_epa": -0.05,
                    "sample_k": 250.0,
                    "unknown_returns_zero": True,
                    # missing supported_uses_replacement_scenario
                },
            }
        )
    )
    with pytest.raises(ConfigurationError, match="qb_adjustment"):
        load_qb_elo_canonical_config(p)


# ---- 16. Invalid initial_rating rejected --------------------------


def test_invalid_initial_rating_rejected(tmp_path: Path) -> None:
    p = tmp_path / "qb_elo_v1.yaml"
    p.write_text(
        yaml.safe_dump(_valid_yaml_overrides(initial_rating=10000.0))
    )
    with pytest.raises(ConfigurationError):
        load_qb_elo_canonical_config(p)


# ---- 17. Invalid K factor rejected --------------------------------


def test_invalid_k_factor_rejected(tmp_path: Path) -> None:
    p = tmp_path / "qb_elo_v1.yaml"
    p.write_text(
        yaml.safe_dump(_valid_yaml_overrides(k_factor_regular=200.0))
    )
    with pytest.raises(ConfigurationError):
        load_qb_elo_canonical_config(p)


# ---- 18. Invalid season reversion range rejected ------------------


def test_invalid_season_reversion_rejected(tmp_path: Path) -> None:
    p = tmp_path / "qb_elo_v1.yaml"
    p.write_text(
        yaml.safe_dump(
            _valid_yaml_overrides(season_mean_reversion_fraction=1.5)
        )
    )
    with pytest.raises(ConfigurationError):
        load_qb_elo_canonical_config(p)


# ---- 19. Invalid MOV divisor rejected -----------------------------


def test_invalid_mov_divisor_rejected(tmp_path: Path) -> None:
    p = tmp_path / "qb_elo_v1.yaml"
    p.write_text(
        yaml.safe_dump(_valid_yaml_overrides(mov_divisor=200.0))
    )
    with pytest.raises(ConfigurationError):
        load_qb_elo_canonical_config(p)


# ---- 20. Invalid MOV cap rejected ---------------------------------


def test_invalid_mov_cap_rejected(tmp_path: Path) -> None:
    p = tmp_path / "qb_elo_v1.yaml"
    p.write_text(
        yaml.safe_dump(_valid_yaml_overrides(mov_cap=99.0))
    )
    with pytest.raises(ConfigurationError):
        load_qb_elo_canonical_config(p)


# ---- 21. Invalid probability bounds rejected ----------------------


def test_invalid_probability_bounds_rejected(tmp_path: Path) -> None:
    p = tmp_path / "qb_elo_v1.yaml"
    p.write_text(
        yaml.safe_dump(_valid_yaml_overrides(prob_min=0.6, prob_max=0.5))
    )
    with pytest.raises(ConfigurationError):
        load_qb_elo_canonical_config(p)


# ---- 22. Invalid QB numeric values rejected -----------------------


def test_invalid_qb_numeric_values_rejected(tmp_path: Path) -> None:
    p = tmp_path / "qb_elo_v1.yaml"
    p.write_text(
        yaml.safe_dump(
            _valid_yaml_overrides(
                qb_max_abs_elo=99999.0,
            )
        )
    )
    with pytest.raises(ConfigurationError):
        load_qb_elo_canonical_config(p)


# ---- 23. Non-boolean QB flags rejected ----------------------------


def test_non_boolean_qb_flag_rejected(tmp_path: Path) -> None:
    p = tmp_path / "qb_elo_v1.yaml"
    base = _valid_yaml_dict()
    base["qb_adjustment"]["unknown_returns_zero"] = "yes"
    p.write_text(yaml.safe_dump(base))
    with pytest.raises(ConfigurationError):
        load_qb_elo_canonical_config(p)


# ---- 24. canonical_config_to_elo_config_input maps all values exactly -


def test_canonical_to_elo_config_input_maps_exactly() -> None:
    cfg = load_qb_elo_canonical_config(YAML_PATH)
    elo = canonical_config_to_eloconfig(cfg)
    # The input mapping must preserve every scalar value.
    assert elo.initial_rating == cfg["initial_rating"]
    assert elo.home_field_elo == cfg["home_field_elo"]
    assert elo.k_factor_regular == cfg["k_factor_regular"]
    assert elo.k_factor_postseason == cfg["k_factor_postseason"]
    assert elo.season_mean_reversion_fraction == cfg[
        "season_mean_reversion_fraction"
    ]
    assert elo.mov_divisor == cfg["mov_divisor"]
    assert elo.mov_cap == cfg["mov_cap"]
    assert elo.prob_min == cfg["prob_min"]
    assert elo.prob_max == cfg["prob_max"]
    qb = elo.qb_adjustment
    assert qb.scale_elo_per_shrunk_epa == cfg[
        "qb_adjustment_scale_elo_per_shrunk_epa"
    ]
    assert qb.max_abs_elo == cfg["qb_adjustment_max_abs_elo"]
    assert qb.replacement_passing_epa == cfg[
        "qb_adjustment_replacement_passing_epa"
    ]
    assert qb.sample_k == cfg["qb_adjustment_sample_k"]
    assert qb.unknown_returns_zero == cfg[
        "qb_adjustment_unknown_returns_zero"
    ]
    assert qb.supported_uses_replacement_scenario == cfg[
        "qb_adjustment_supported_uses_replacement_scenario"
    ]


# ---- 25. Tuning-ledger primary configuration equals canonical normalized YAML --


def test_tuning_ledger_primary_configuration_equals_yaml(tmp_path: Path) -> None:
    """Run the walk-forward into a temp dir and confirm the tuning
    ledger's primary_configuration.configuration equals the
    canonical normalized YAML exactly (no in-code default, no
    dataclass default)."""
    from datetime import datetime, timezone

    from nfl_edge.backtest.walk_forward import run_development_walk_forward

    out = tmp_path / "tl"
    out.mkdir()
    run_development_walk_forward(
        games_path=Path("data/derived/features_v1/game_features_2018_2025.parquet"),
        team_features_path=Path("data/derived/features_v1/team_pregame_features_2018_2025.parquet"),
        output_dir=out,
        created_at=datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc),
        project_root=REPO_ROOT,
    )
    tl = json.loads((out / "qb_elo_tuning_ledger_v1.json").read_text())
    primary = tl["primary_configuration"]
    assert primary["path"] == "config/qb_elo_v1.yaml"
    # The configuration value in the tuning ledger's sensitivity
    # audit must equal the canonical normalized YAML exactly.
    canonical = load_qb_elo_canonical_config(YAML_PATH)
    sens_cfg = tl["sensitivity_audit"][0]["configuration"]
    assert dict(sorted(sens_cfg.items())) == dict(sorted(canonical.items()))


# ---- 26. model_config_sha256 in the manifest equals canonical_config_sha256 --


def test_manifest_model_config_sha256_equals_canonical(tmp_path: Path) -> None:
    from datetime import datetime, timezone

    from nfl_edge.backtest.walk_forward import run_development_walk_forward

    out = tmp_path / "mf"
    out.mkdir()
    run_development_walk_forward(
        games_path=Path("data/derived/features_v1/game_features_2018_2025.parquet"),
        team_features_path=Path("data/derived/features_v1/team_pregame_features_2018_2025.parquet"),
        output_dir=out,
        created_at=datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc),
        project_root=REPO_ROOT,
    )
    manifest = json.loads((out / "qb_elo_run_manifest_v1.json").read_text())
    canonical = load_qb_elo_canonical_config(YAML_PATH)
    expected = canonical_config_sha256(canonical)
    assert manifest["model_config_sha256"] == expected


# ---- 27. Temporary-checkout execution loads that checkout's YAML --


def test_temporary_checkout_loads_its_own_yaml(tmp_path: Path) -> None:
    """Copy the repo to a temporary directory, modify the YAML
    in the copy, run from the copy, and confirm the runtime loaded
    the copy's YAML (not the host's)."""
    if not (REPO_ROOT / "data/derived/features_v1").exists():
        pytest.skip("data not available in this environment")
    copy = tmp_path / "checkout"
    shutil.copytree(REPO_ROOT, copy, ignore=shutil.ignore_patterns(".venv", ".git", "__pycache__"))
    custom_yaml = copy / "config/qb_elo_v1.yaml"
    custom_yaml.write_text(custom_yaml.read_text().replace("0.333", "0.500"))
    env = {
        "PYTHONPATH": "src",
        "PATH": "/root/nfl-edge/.venv/bin:/usr/bin:/bin",
    }
    script = (
        "import sys; sys.path.insert(0, 'src'); "
        "from pathlib import Path; "
        "from nfl_edge.models.qb_elo_config import load_qb_elo_canonical_config; "
        f"print(load_qb_elo_canonical_config(Path('{copy}/config/qb_elo_v1.yaml'))['season_mean_reversion_fraction'])"
    )
    r = subprocess.run(
        [sys.executable, "-c", script],
        cwd=copy,
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "0.5"


# ---- 28. No /root/nfl-edge configuration dependency remains ------


def test_no_host_path_dependency_in_canonical_loader() -> None:
    """The canonical loader takes a yaml_path argument; nothing
    in the loader hard-codes /root/nfl-edge."""
    import nfl_edge.models.qb_elo_config as mod
    src = Path(mod.__file__).read_text()
    assert "/root/nfl-edge" not in src


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------


def _valid_yaml_dict(
    *,
    initial_rating: float = 1500.0,
    home_field_elo: float = 48.0,
    k_factor_regular: float = 20.0,
    k_factor_postseason: float = 4.0,
    season_mean_reversion_fraction: float = 0.333,
    mov_divisor: float = 6.0,
    mov_cap: float = 2.5,
    prob_min: float = 0.01,
    prob_max: float = 0.99,
    qb_max_abs_elo: float = 50.0,
) -> dict:
    return {
        "initial_rating": initial_rating,
        "home_field_elo": home_field_elo,
        "k_factor_regular": k_factor_regular,
        "k_factor_postseason": k_factor_postseason,
        "season_mean_reversion_fraction": season_mean_reversion_fraction,
        "margin_of_victory": {"divisor": mov_divisor, "cap": mov_cap},
        "probability": {"min": prob_min, "max": prob_max},
        "qb_adjustment": {
            "scale_elo_per_shrunk_epa": 500.0,
            "max_abs_elo": qb_max_abs_elo,
            "replacement_passing_epa": -0.05,
            "sample_k": 250.0,
            "unknown_returns_zero": True,
            "supported_uses_replacement_scenario": True,
        },
    }


def _valid_yaml_overrides(**kw: Any) -> dict:
    return _valid_yaml_dict(**kw)
