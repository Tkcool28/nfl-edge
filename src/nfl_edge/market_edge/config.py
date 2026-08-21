"""Fail-closed load of the frozen Market Edge preregistration config.

Any downstream analysis MUST load the config through this module and reject a
changed fingerprint. The config self-declares ``fingerprint.sha256_self`` and
is frozen at ``d19534094...2e5c``; the canonical content hash must reproduce
that value or the process raises (it never silently proceeds with changed
methodology).

The canonicalization is byte-for-byte identical to the value pinned by the
preregistration contract tests (`tests/contracts/test_market_edge_preregistration_v1.py`
→ `scripts/freeze_market_edge_prereg.py::canonicalize`).
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import yaml

PINNED_FINGERPRINT = "d195340940e5c9d6c9f62bbfbb8f8f50836013e05334e870f0905d3592d62e5c"


def _canonicalize(text: str) -> str:
    """Reproduce the prereg canonical fingerprint of the config content."""
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "scripts" / "freeze_market_edge_prereg.py"
    spec = importlib.util.spec_from_file_location("freeze_mep", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # provides ``canonicalize``
    return module.canonicalize(text)


def load_pinned_config(config_path: str | Path) -> dict:
    """Load the frozen config and HARD-FAIL if its fingerprint is not pinned."""
    config_path = Path(config_path)
    text = config_path.read_text(encoding="utf-8")
    digest = hashlib.sha256(_canonicalize(text)).hexdigest()
    if digest != PINNED_FINGERPRINT:
        raise RuntimeError(
            f"Market Edge prereg config fingerprint MISMATCH: got {digest} "
            f"expected {PINNED_FINGERPRINT}. Refusing to score under changed "
            f"methodology."
        )
    cfg = yaml.safe_load(text)
    if cfg["fingerprint"].get("sha256_self") != PINNED_FINGERPRINT:
        raise RuntimeError("Config sha256_self field does not match pinned fingerprint.")
    return cfg