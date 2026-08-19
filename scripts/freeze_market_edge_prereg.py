"""Freeze the outcome-blind market-edge preregistration fingerprint.

Computes a deterministic SHA-256 over the canonical serialization of
config/market_edge_validation_v1.yaml with the self-referential field
(fingerprint.sha256_self) neutralized (set to empty string), then stamps
that hash into the config.

Methodology must be frozen BEFORE any outcome inspection. This script only
reads the config; it opens no outcome/scores/ROI data.

Usage:
  PYTHONPATH=src /root/nfl-edge/.venv/bin/python scripts/freeze_market_edge_prereg.py
"""
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "market_edge_validation_v1.yaml"
SELF_HASH_KEY = "sha256_self"
PREFIX = f"{SELF_HASH_KEY}:"


def canonicalize(text: str) -> bytes:
    out: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(PREFIX) and not s.startswith("#"):
            indent = line[: len(line) - len(line.lstrip())]
            out.append(f'{indent}{PREFIX} ""')
        else:
            out.append(line)
    return "\n".join(out).encode("utf-8")


def pin_hash(text: str, digest: str) -> str:
    out: list[str] = []
    hit = 0
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(PREFIX) and not s.startswith("#"):
            indent = line[: len(line) - len(line.lstrip())]
            out.append(f'{indent}{PREFIX} "{digest}"')
            hit += 1
        else:
            out.append(line)
    if hit != 1:
        raise SystemExit(f"error: expected exactly one {SELF_HASH_KEY} field, found {hit}")
    return "\n".join(out)


def main() -> int:
    text = CONFIG.read_text(encoding="utf-8")
    digest = hashlib.sha256(canonicalize(text)).hexdigest()
    CONFIG.write_text(pin_hash(text, digest), encoding="utf-8")
    print(f"FROZEN sha256_self = {digest}")
    print(f"wrote: {CONFIG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())