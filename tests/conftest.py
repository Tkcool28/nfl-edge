"""Pytest conftest: make the audit's test-only stub session importable
under its historical ``_sleeper_fake_session`` name. The canonical
implementation lives in
``tests/source_audits/sleeper_qb_v1/_fake_session.py``; this shim
exposes it so test files can keep the short name."""

import importlib.util
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
SHIM = THIS_DIR / "source_audits" / "sleeper_qb_v1" / "_fake_session.py"

spec = importlib.util.spec_from_file_location("_sleeper_fake_session", SHIM)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)  # type: ignore[union-attr]
sys.modules["_sleeper_fake_session"] = module
