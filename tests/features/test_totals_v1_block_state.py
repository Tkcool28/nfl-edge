"""Tests for immutable block-start state mechanics (Totals V1)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from nfl_edge.backtest.blocks import PredictionBlock
from nfl_edge.features.totals_v1.block_state import (
    Accumulator,
    BlockStartSnapshot,
    GameObservation,
    TeamEntState,
    TotalsBlockState,
)

UTC = timezone.utc


def _block(season, st, week, game_ids):
    return PredictionBlock(
        block_id=f"{season}_{st}_W{week:02d}",
        season=season,
        season_type=st,
        week=week,
        as_of_utc=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        game_ids=tuple(game_ids),
    )


def _obs(block, game_id, team_updates):
    return GameObservation(block_id=block.block_id, game_id=game_id, team_updates=team_updates)


def test_accumulator_add_immutability():
    a = Accumulator()
    b = a.add(2.0, 4.0)
    assert a.numerator == 0.0 and a.denominator == 0.0  # original untouched
    assert b.numerator == 2.0 and b.denominator == 4.0
    c = b.add(1.0, 1.0, sample=1)
    assert c.numerator == 3.0 and c.denominator == 5.0 and c.sample_count == 1
    assert b.denominator == 4.0


def test_two_game_blocks_see_identical_start_state():
    block = _block(2024, "REG", 5, ["g1", "g2"])
    state = TotalsBlockState()
    # seed prior-region state so the snapshot is non-trivial
    prior_block = _block(2024, "REG", 4, ["g0"])
    prior_obs = _obs(prior_block, "g0", {"KC": {"epa_play": (5.0, 5.0, 5)}})
    state.commit_block(prior_block, [prior_obs])
    snap = state.snapshot_for_block(block)
    # both games read the same frozen snapshot
    s1 = snap.team("KC")
    s2 = snap.team("KC")
    assert s1 is s2  # same immutable object


def test_game_a_cannot_alter_game_b_entering_state():
    # Two separate single-game blocks demonstrate that a committed game cannot
    # mutate the still-frozen snapshot of a subsequent block (cross-block, not
    # same-block — same-block same-team state is enforced by the complete-block
    # invariant and covered by the dedicated partial-block test).
    block_a = _block(2024, "REG", 5, ["gA"])
    block_b = _block(2024, "REG", 6, ["gB"])
    state = TotalsBlockState()
    snap_a = state.snapshot_for_block(block_a)
    # gA is emitted from snap_a; its observation is collected separately
    obsA = _obs(block_a, "gA", {"KC": {"pts": (7.0, 1.0, 1)}})
    # gA's observation must not leak into snap_a itself
    assert snap_a.team("KC").get("pts") is None
    # committing (post-block) must not change the already-captured snapshot
    state.commit_block(block_a, [obsA])
    assert snap_a.team("KC").get("pts") is None  # frozen snapshot unchanged
    assert state.team_state("KC").get("pts").denominator == 1.0
    # the next block's snapshot reads the committed running state
    snap_b = state.snapshot_for_block(block_b)
    assert snap_b.team("KC").get("pts").numerator == 7.0


def test_post_block_update_changes_next_block():
    block1 = _block(2024, "REG", 5, ["gA"])
    block2 = _block(2024, "REG", 6, ["gB"])
    state = TotalsBlockState()
    snap1 = state.snapshot_for_block(block1)
    # emit block1 games from snap1, observe, then commit after block complete
    state.commit_block(block1, [_obs(block1, "gA", {"KC": {"pts": (7.0, 1.0, 1)}})])
    snap2 = state.snapshot_for_block(block2)
    assert snap1.team("KC").get("pts") is None
    assert snap2.team("KC").get("pts").numerator == 7.0


def test_shuffled_game_order_cannot_alter_frozen_snapshot():
    block = _block(2024, "REG", 5, ["gA", "gB"])
    state = TotalsBlockState()
    snap = state.snapshot_for_block(block)
    # commit in a shuffled order; then re-create with a different order and
    # confirm the committed result is identical (deterministic).
    s1 = TotalsBlockState()
    s2 = TotalsBlockState()
    s1.commit_block(block, [
        _obs(block, "gB", {"KC": {"x": (1.0, 1.0, 1)}}),
        _obs(block, "gA", {"KC": {"x": (2.0, 1.0, 1)}}),
    ])
    s2.commit_block(block, [
        _obs(block, "gA", {"KC": {"x": (2.0, 1.0, 1)}}),
        _obs(block, "gB", {"KC": {"x": (1.0, 1.0, 1)}}),
    ])
    assert s1.team_state("KC").get("x").numerator == s2.team_state("KC").get("x").numerator == 3.0
    assert snap.team("KC").get("x") is None  # frozen snap unaffected


def test_deterministic_post_block_update_batch_across_games():
    block = _block(2024, "REG", 5, ["gA", "gB"])
    state = TotalsBlockState()
    state.commit_block(block, [
        _obs(block, "gA", {"KC": {"epa": (1.0, 2.0, 2)}}),
        _obs(block, "gB", {"KC": {"epa": (3.0, 1.0, 1)}, "BAL": {"epa": (9.0, 3.0, 3)}}),
    ])
    kc = state.team_state("KC").get("epa")
    bal = state.team_state("BAL").get("epa")
    assert kc.numerator == 4.0 and kc.denominator == 3.0
    assert bal.numerator == 9.0 and bal.denominator == 3.0


def test_snapshot_is_immutable_to_commit():
    block = _block(2024, "REG", 5, ["gA"])
    state = TotalsBlockState()
    snap = state.snapshot_for_block(block)
    teams_before = dict(snap.teams)
    state.commit_block(block, [_obs(block, "gA", {"KC": {"epa": (1.0, 1.0, 1)}})])
    assert snap.teams == teams_before
    assert isinstance(snap, BlockStartSnapshot)


def test_team_ent_state_default_empty():
    st = TeamEntState()
    assert st.get("anything") is None
    st2 = st.with_metric("m", Accumulator(1.0, 1.0))
    assert st2.get("m").numerator == 1.0


def test_multi_metric_same_team_accumulate_independently():
    """One team in one game can update at least two distinct metrics independently."""
    # Single-game block — multi-metric independence is a per-game property.
    block = _block(2024, "REG", 5, ["g1"])
    state = TotalsBlockState()
    state.commit_block(block, [
        _obs(block, "g1", {"KC": {"epa_play": (3.0, 3.0, 3), "success": (2.0, 3.0, 3)}}),
    ])
    kc = state.team_state("KC")
    assert kc.get("epa_play").numerator == 3.0 and kc.get("epa_play").denominator == 3.0
    assert kc.get("success").numerator == 2.0 and kc.get("success").denominator == 3.0
    # A second (single-game) block for "g2" advances only one of those metrics
    # and adds a new one, proving each metric accumulates independently across
    # blocks without cross-pollution.
    block2 = _block(2024, "REG", 6, ["g2"])
    state.commit_block(block2, [
        _obs(block2, "g2", {"KC": {"epa_play": (1.0, 2.0, 2), "sacks_dropback": (1.0, 2.0, 2)}}),
    ])
    kc = state.team_state("KC")
    assert kc.get("epa_play").numerator == 4.0 and kc.get("epa_play").denominator == 5.0
    assert kc.get("success").denominator == 3.0  # untouched by the second block
    assert kc.get("sacks_dropback").numerator == 1.0


def test_two_games_same_block_see_same_frozen_entering_snapshot():
    block = _block(2024, "REG", 8, ["g1", "g2"])
    state = TotalsBlockState()
    # seed a prior block so KC exists in the running state
    prior = _block(2024, "REG", 7, ["g0"])
    state.commit_block(prior, [_obs(prior, "g0", {"KC": {"epa": (4.0, 2.0, 2)}})])
    snap = state.snapshot_for_block(block)
    # both games in the block must read the identical frozen snapshot object
    assert snap.team("KC") is snap.team("KC")
    # and a fresh TeamEntState is only returned for an unseeded team
    assert snap.team("NOBODY") == TeamEntState()


def test_wrong_block_id_hard_fails():
    block = _block(2024, "REG", 5, ["g1"])
    state = TotalsBlockState()
    other = _block(2024, "REG", 6, ["g1"])
    with pytest.raises(ValueError, match="block_id"):
        state.commit_block(block, [_obs(other, "g1", {"KC": {"x": (1.0, 1.0, 1)}})])


def test_game_not_in_block_hard_fails():
    block = _block(2024, "REG", 5, ["g1"])
    state = TotalsBlockState()
    with pytest.raises(ValueError, match="not in block"):
        state.commit_block(block, [_obs(block, "g999", {"KC": {"x": (1.0, 1.0, 1)}})])


def test_duplicate_game_observation_ambiguous_hard_fails():
    block = _block(2024, "REG", 5, ["g1", "g1b"])
    state = TotalsBlockState()
    # two observations naming the same game_id in one commit is ambiguous,
    # AND violates the complete-block invariant (g1b is missing). Either
    # path must reject the commit.
    with pytest.raises(ValueError, match="ambiguous"):
        state.commit_block(block, [
            _obs(block, "g1", {"KC": {"x": (1.0, 1.0, 1)}}),
            _obs(block, "g1", {"KC": {"y": (2.0, 1.0, 1)}}),
        ])


def test_shuffled_multi_metric_ordering_produces_identical_state():
    block = _block(2024, "REG", 5, ["g1", "g2"])
    obs_a = [
        _obs(block, "g1", {"KC": {"epa": (1.0, 1.0, 1), "success": (2.0, 1.0, 1)}}),
        _obs(block, "g2", {"KC": {"epa": (3.0, 1.0, 1)}, "BAL": {"success": (5.0, 1.0, 1)}}),
    ]
    obs_b = [
        _obs(block, "g2", {"KC": {"epa": (3.0, 1.0, 1)}, "BAL": {"success": (5.0, 1.0, 1)}}),
        _obs(block, "g1", {"KC": {"epa": (1.0, 1.0, 1), "success": (2.0, 1.0, 1)}}),
    ]
    s1, s2 = TotalsBlockState(), TotalsBlockState()
    s1.commit_block(block, obs_a)
    s2.commit_block(block, obs_b)
    assert s1.team_state("KC").get("epa") == s2.team_state("KC").get("epa")
    assert s1.team_state("KC").get("success") == s2.team_state("KC").get("success")
    assert s1.team_state("BAL").get("success") == s2.team_state("BAL").get("success")


# ---------------------------------------------------------------------------
# Complete-block commit invariant — Phase 3A targeted fix
# ---------------------------------------------------------------------------


def test_partial_block_commit_hard_fails():
    """A two-game block committed with only one observation must be rejected.

    The error must make clear the commit does not cover the complete block.
    """
    block = _block(2024, "REG", 5, ["gA", "gB"])
    state = TotalsBlockState()
    with pytest.raises(ValueError, match="does not cover the complete block"):
        state.commit_block(block, [
            _obs(block, "gA", {"KC": {"epa": (1.0, 2.0, 2)}}),
        ])
    # the running state must be unchanged after a rejected partial commit
    assert state.team_state("KC").get("epa") is None


def test_empty_update_game_counts_toward_completeness():
    """A two-game block succeeds when one game carries empty team_updates."""
    block = _block(2024, "REG", 5, ["gA", "gB"])
    state = TotalsBlockState()
    state.commit_block(block, [
        _obs(block, "gA", {"KC": {"epa": (1.0, 2.0, 2)}}),
        _obs(block, "gB", {}),  # no qualifying metric updates, but present
    ])
    kc = state.team_state("KC").get("epa")
    assert kc.numerator == 1.0 and kc.denominator == 2.0


def test_empty_update_game_still_requires_no_silent_synthesis():
    """If the caller forgets to pass the empty-update GameObservation, the
    commit must fail — the implementation must not silently synthesize one.
    """
    block = _block(2024, "REG", 5, ["gA", "gB"])
    state = TotalsBlockState()
    with pytest.raises(ValueError, match="does not cover the complete block"):
        state.commit_block(block, [
            _obs(block, "gA", {"KC": {"epa": (1.0, 2.0, 2)}}),
            # intentionally omitting gB — no silent synthesis
        ])


def test_full_two_game_block_commits_successfully():
    block = _block(2024, "REG", 5, ["gA", "gB"])
    state = TotalsBlockState()
    state.commit_block(block, [
        _obs(block, "gA", {"KC": {"epa": (1.0, 2.0, 2)}}),
        _obs(block, "gB", {"KC": {"epa": (3.0, 1.0, 1)}, "BAL": {"epa": (9.0, 3.0, 3)}}),
    ])
    assert state.team_state("KC").get("epa").numerator == 4.0
    assert state.team_state("KC").get("epa").denominator == 3.0
    assert state.team_state("BAL").get("epa").numerator == 9.0


def test_shuffled_full_block_is_deterministic():
    """Committing [gA, gB] and [gB, gA] separately must yield identical state."""
    block = _block(2024, "REG", 5, ["gA", "gB"])
    s1, s2 = TotalsBlockState(), TotalsBlockState()
    s1.commit_block(block, [
        _obs(block, "gA", {"KC": {"x": (2.0, 1.0, 1)}}),
        _obs(block, "gB", {"KC": {"x": (1.0, 1.0, 1)}}),
    ])
    s2.commit_block(block, [
        _obs(block, "gB", {"KC": {"x": (1.0, 1.0, 1)}}),
        _obs(block, "gA", {"KC": {"x": (2.0, 1.0, 1)}}),
    ])
    n1 = s1.team_state("KC").get("x")
    n2 = s2.team_state("KC").get("x")
    assert n1 == n2
    assert n1.numerator == 3.0 and n1.denominator == 2.0


def test_frozen_block_start_preserved_against_partial_commit():
    """Even if the caller attempts a partial commit, the pre-block snapshot
    must remain frozen AND must not be polluted by any committed game in the
    same block. Only after the COMPLETE block commit does the next snapshot
    see the update.
    """
    block = _block(2024, "REG", 5, ["gA", "gB"])
    state = TotalsBlockState()
    snap = state.snapshot_for_block(block)
    # Both games read the frozen snapshot — neither sees any metric yet.
    assert snap.team("KC").get("epa") is None
    assert snap.team("BAL").get("epa") is None
    # A partial commit must be rejected; the snapshot remains frozen and
    # the running state remains untouched.
    with pytest.raises(ValueError, match="does not cover the complete block"):
        state.commit_block(block, [
            _obs(block, "gA", {"KC": {"epa": (1.0, 2.0, 2)}}),
        ])
    assert snap.team("KC").get("epa") is None  # frozen snapshot unchanged
    assert state.team_state("KC").get("epa") is None  # running state untouched
    # Only after the COMPLETE block commit does the next snapshot see updates.
    state.commit_block(block, [
        _obs(block, "gA", {"KC": {"epa": (1.0, 2.0, 2)}}),
        _obs(block, "gB", {"KC": {"epa": (3.0, 1.0, 1)}, "BAL": {"epa": (9.0, 3.0, 3)}}),
    ])
    snap_next = state.snapshot_for_block(_block(2024, "REG", 6, ["gZ"]))
    assert snap_next.team("KC").get("epa").numerator == 4.0
    assert snap_next.team("BAL").get("epa").numerator == 9.0
    # And the original snapshot for block 5 still reads the empty pre-state.
    assert snap.team("KC").get("epa") is None