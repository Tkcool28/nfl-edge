"""Strictly-prior season-week uncertainty for accepted Task05F evaluators."""
from __future__ import annotations

import random
from collections import defaultdict

from .contracts import ReliabilityState

MIN_ROWS = 128
MIN_BLOCKS = 4
STABILITY_MAX_RADIUS = 0.05


def block_bootstrap_calibration_radius(
    rows: list[tuple[str, float, int]],
    *,
    replicates: int = 1000,
    seed: int = 20260820,
    quantile: float = 0.90,
) -> float:
    if not rows:
        raise ValueError("uncertainty radius requires at least one row")
    blocks: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for block, probability, outcome in rows:
        blocks[str(block)].append((float(probability), int(outcome)))
    keys = sorted(blocks)
    if len(keys) < 2:
        return 0.10
    rng = random.Random(int(seed))
    vals: list[float] = []
    for _ in range(int(replicates)):
        sample: list[tuple[float, int]] = []
        for _ in keys:
            sample.extend(blocks[rng.choice(keys)])
        vals.append(abs(sum(p - y for p, y in sample) / len(sample)))
    vals.sort()
    idx = min(len(vals) - 1, max(0, int(round((len(vals) - 1) * float(quantile)))))
    return float(vals[idx])


def fit_reliability_state(
    rows: list[tuple[str, float, int]],
    *,
    minimum_rows: int = MIN_ROWS,
    minimum_blocks: int = MIN_BLOCKS,
    stability_max_radius: float = STABILITY_MAX_RADIUS,
) -> ReliabilityState:
    n = len(rows)
    block_count = len({str(block) for block, _, _ in rows})
    if n < int(minimum_rows):
        return ReliabilityState(None, n, block_count, False)
    radius = block_bootstrap_calibration_radius(rows)
    stable = block_count >= int(minimum_blocks) and radius <= float(stability_max_radius)
    return ReliabilityState(float(radius), n, block_count, bool(stable))
