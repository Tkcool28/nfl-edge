#!/usr/bin/env python3
"""Run one bounded NFL EDGE production refresh cycle."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nfl_edge.operations.production_refresh_v1 import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
