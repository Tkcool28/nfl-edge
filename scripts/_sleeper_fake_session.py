"""Thin compatibility shim for ``scripts/_sleeper_fake_session.py``.

The test-only stub HTTP session lives in
``tests/source_audits/sleeper_qb_v1/_fake_session.py`` so the test
suite does not need to import from ``scripts/``. This module re-exports
the same classes under the historical name so the CLI can keep using
``--use-fake-session`` without duplication.
"""

from tests.source_audits.sleeper_qb_v1._fake_session import (
    FakeSleeperResponse,
    FakeSleeperSession,
    _fake_player_map,
)

__all__ = ["FakeSleeperResponse", "FakeSleeperSession", "_fake_player_map"]
