from __future__ import annotations
import random
from collections import defaultdict

# Stability rule: an evaluator is evidenced-stable only when it has >= min_blocks
# distinct prior season-week blocks AND its block-bootstrap 0.90-quantile
# calibration-gap radius over those prior blocks is bounded (<= max_radius).
# Block-bootstrap radius is the preregistered bounded per-block calibration
# statistic; a large radius reflects materially volatile/biased recent blocks.
MIN_STABLE_BLOCKS = 4
STABILITY_MAX_RADIUS = 0.05


def block_calibration_gaps(rows: list[tuple[str, float, int]]) -> dict[str, float]:
    blocks: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for b, p, y in rows:
        blocks[str(b)].append((float(p), int(y)))
    gaps = {}
    for b, items in blocks.items():
        gaps[b] = sum(p - y for p, y in items) / len(items)
    return gaps


def _block_count(rows: list[tuple[str, float, int]]) -> int:
    return len({str(b) for b, _, _ in rows})


def calibration_stability(rows: list[tuple[str, float, int]],
                          min_blocks: int = MIN_STABLE_BLOCKS,
                          max_radius: float = STABILITY_MAX_RADIUS) -> bool:
    """Bounded prior-block calibration stability evidence (requires a radius)."""
    if not rows:
        return False
    if len({str(b) for b, _, _ in rows}) < min_blocks:
        return False
    radius = block_bootstrap_calibration_radius(rows, quantile=0.90)
    return radius <= max_radius


def stability_from_radius(rows: list[tuple[str, float, int]],
                          radius: float,
                          min_blocks: int = MIN_STABLE_BLOCKS,
                          max_radius: float = STABILITY_MAX_RADIUS) -> bool:
    """Stability using an already-computed block-bootstrap radius (no recompute)."""
    if not rows:
        return False
    if len({str(b) for b, _, _ in rows}) < min_blocks:
        return False
    return radius <= max_radius


def block_bootstrap_calibration_radius(rows: list[tuple[str, float, int]], replicates: int = 1000, seed: int = 20260820, quantile: float = .90) -> float:
    """Season-week block bootstrap of absolute mean calibration gap."""
    if not rows:
        return 1.0
    blocks = {}
    for b, p, y in rows:
        blocks.setdefault(str(b), []).append((p, y))
    keys = list(blocks)
    if len(keys) < 2:
        return 0.10
    rng = random.Random(seed)
    vals = []
    for _ in range(replicates):
        sample = []
        for _ in keys:
            sample.extend(blocks[rng.choice(keys)])
        vals.append(abs(sum(p - y for p, y in sample) / len(sample)))
    vals.sort()
    idx = min(len(vals) - 1, max(0, int(round((len(vals) - 1) * quantile))))
    return float(vals[idx])

