"""Immutable block-start state mechanics for Totals V1.

Phase 3A provides only the deterministic state container/mechanics needed so
that later feature aggregations (Phase 3B) can follow the contract rules:

1. snapshot one immutable team entering-state before a target prediction block;
2. every game in that block reads the same frozen snapshot;
3. current-block observations are collected separately;
4. only after the complete target block is emitted may observations update state;
5. update order is deterministic;
6. a target game's state can never affect another game in the same block.

This module deliberately does NOT implement EPA/play, pace, red-zone, or any
feature-family formulas. It only provides the accumulator and freeze/commit
mechanics.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Mapping

from ...backtest.blocks import PredictionBlock

TeamId = str
MetricName = str


@dataclass(frozen=True)
class Accumulator:
    """A deterministic numerator/denominator accumulator (optionally with a sample count).

    Immutable: every operation returns a new instance. This is the smallest
    abstraction the accepted contract needs; later families add keys keyed by
    metric name.
    """

    numerator: float = 0.0
    denominator: float = 0.0
    sample_count: int = 0

    def add(self, numerator: float, denominator: float, sample: int = 0) -> "Accumulator":
        """Return a new accumulator with the given observation added."""
        return Accumulator(
            numerator=self.numerator + numerator,
            denominator=self.denominator + denominator,
            sample_count=self.sample_count + sample,
        )

    def merge(self, other: "Accumulator") -> "Accumulator":
        """Return a new accumulator combining two accumulators deterministically."""
        return Accumulator(
            numerator=self.numerator + other.numerator,
            denominator=self.denominator + other.denominator,
            sample_count=self.sample_count + other.sample_count,
        )


@dataclass(frozen=True)
class TeamEntState:
    """Immutable per-team entering-state: a mapping of metric -> accumulator."""

    metrics: Mapping[MetricName, Accumulator] = field(default_factory=dict)

    def get(self, metric: MetricName) -> Accumulator | None:
        return self.metrics.get(metric)

    def with_metric(self, metric: MetricName, value: Accumulator) -> "TeamEntState":
        return replace(self, metrics={**self.metrics, metric: value})


@dataclass(frozen=True)
class BlockStartSnapshot:
    """The frozen entering-state for one prediction block.

    Built once before any game in the block is emitted. Every game in the
    block reads from this same immutable snapshot.
    """

    block_id: str
    teams: Mapping[TeamId, TeamEntState] = field(default_factory=dict)

    def team(self, team: TeamId) -> TeamEntState:
        return self.teams.get(team, TeamEntState())


@dataclass(frozen=True)
class GameObservation:
    """A completed-game observation to be applied only after its block is emitted.

    ``team_updates`` maps team -> metric -> (numerator, denominator, sample)
    additive observation, so a single game can carry multiple metric
    accumulations for the same team (e.g. ``epa_play``, ``success``, and
    ``sacks_dropback`` for one offense). Keep semantics minimal; later families
    map their own formulas on top of these.
    """

    block_id: str
    game_id: str
    team_updates: Mapping[TeamId, Mapping[MetricName, tuple[float, float, int]]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.game_id:
            raise ValueError("GameObservation requires a game_id")


@dataclass
class TotalsBlockState:
    """Mutable-running Totals state with immutable block-start snapshotting.

    Usage:
        state = TotalsBlockState()
        snap = state.snapshot_for_block(target_block)   # frozen, immutable
        # emit all games in target_block from `snap`
        state.commit_block(target_block, observations)  # after block complete
    """

    _teams: dict[TeamId, TeamEntState] = field(default_factory=dict)

    def snapshot_for_block(self, block: PredictionBlock) -> BlockStartSnapshot:
        """Return an immutable entering-state snapshot for a block.

        The returned snapshot is a frozen copy of the current running state;
        later commits do not mutate it.
        """
        frozen = {team: state for team, state in self._teams.items()}
        return BlockStartSnapshot(block_id=block.block_id, teams=frozen)

    def commit_block(
        self,
        block: PredictionBlock,
        observations: list[GameObservation],
    ) -> None:
        """Apply all completed-block observations after the block is fully emitted.

        Hard safety validation before applying anything:

        - an observation whose ``block_id`` differs from ``block.block_id``
          raises (no observation from another block may update this block);
        - an observation whose ``game_id`` is not contained in ``block.game_ids``
          raises (no observation from another game may update this block);
        - two observations that name the same ``game_id`` within one commit
          raise, because that double-count makes update semantics ambiguous;
        - the set of observation ``game_id`` values MUST equal
          ``set(block.game_ids)`` exactly: every block game must appear
          exactly once. A partial block commit (missing a game) is rejected
          so a target game's observation cannot leak into a future snapshot
          while another game in the same block is still pending. A game
          that has no qualifying metric updates is still represented by a
          ``GameObservation(..., team_updates={})`` so block completeness is
          preserved without inventing observations; missing observations are
          not silently synthesized.

        Within a game each team's updates may carry multiple distinct metrics,
        and each metric accumulates independently. Update order is
        deterministic: observations sorted by block_id then game_id, teams
        ascending, metrics ascending. All observations for the target block are
        applied together after the block is complete.
        """
        for obs in observations:
            if obs.block_id != block.block_id:
                raise ValueError(
                    f"observation block_id {obs.block_id!r} does not match "
                    f"commit block {block.block_id!r}"
                )
            if obs.game_id not in block.game_ids:
                raise ValueError(
                    f"observation game_id {obs.game_id!r} not in block game_ids "
                    f"{block.game_ids}"
                )

        seen_games: set[str] = set()
        for obs in observations:
            if obs.game_id in seen_games:
                raise ValueError(
                    f"duplicate observation for game_id {obs.game_id!r} "
                    f"in block {block.block_id!r} makes update semantics ambiguous"
                )
            seen_games.add(obs.game_id)

        # Complete-block invariant: every game in the block must be represented
        # exactly once. A partial commit would let a future snapshot observe
        # the committed game's metrics while another game in the same block is
        # still pending, which is same-block leakage.
        block_games = set(block.game_ids)
        if seen_games != block_games:
            missing = sorted(block_games - seen_games)
            extra = sorted(seen_games - block_games)
            if missing:
                raise ValueError(
                    f"commit_block does not cover the complete block "
                    f"{block.block_id!r}: missing observation(s) for game_id(s) "
                    f"{missing}; every block game must appear exactly once. "
                    f"Games with no qualifying metric updates must still be "
                    f"represented by GameObservation(..., team_updates={{}})."
                )
            if extra:
                raise ValueError(
                    f"commit_block received observation(s) for game_id(s) "
                    f"{extra} that are not in block {block.block_id!r} "
                    f"(game_ids={block.game_ids})"
                )

        # Group per-team, per-metric additive updates across all observations.
        updates_by_team: dict[TeamId, dict[MetricName, Accumulator]] = {}
        for obs in sorted(observations, key=lambda o: (o.block_id, o.game_id)):
            for team in sorted(obs.team_updates.keys()):
                for metric in sorted(obs.team_updates[team].keys()):
                    numerator, denominator, sample = obs.team_updates[team][metric]
                    per_team = updates_by_team.setdefault(team, {})
                    per_team[metric] = (per_team.get(metric) or Accumulator()).add(
                        numerator, denominator, sample
                    )
        # Apply deterministically: team asc, then metric asc.
        for team in sorted(updates_by_team.keys()):
            state = self._teams.get(team, TeamEntState())
            for metric in sorted(updates_by_team[team].keys()):
                current = state.get(metric) or Accumulator()
                state = state.with_metric(metric, current.merge(updates_by_team[team][metric]))
            self._teams[team] = state

    def team_state(self, team: TeamId) -> TeamEntState:
        return self._teams.get(team, TeamEntState())
