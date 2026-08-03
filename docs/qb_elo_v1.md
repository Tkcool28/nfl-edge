# QB-Elo v1 — Development Baseline

## Overview
This document describes the QB-adjusted Elo model that serves as the 
**development baseline** for NFL Edge. Task 03A establishes this baseline
on the 2018–2024 development window. The 2025 season is sealed holdout
and is never used for fit, prediction, scoring, or reporting.

## Formula (Textbook NFL Elo)

### Expected win probability (home perspective)
$$E_H = \frac{1}{1 + 10^{(E_A - E_H - HFA) / 400}}$$

Where:
- $E_H$ = home team's Elo before the game
- $E_A$ = away team's Elo before the game
- $HFA$ = home-field advantage (in Elo points); 0 for neutral site

### QB-adjusted Elo difference
$$\Delta_{adj} = (E_H + HFA + q_H) - (E_A + q_A)$$

Where $q_H$ and $q_A$ are zero-point QB adjustments (see below).

### Final probability
$$P(\text{home win}) = \frac{1}{1 + 10^{-\Delta_{adj} / 400}}$$

Clamped to $[0.01, 0.99]$ for numerical safety only.

## Elo Update

After the game is complete (outcome persisted in the state ledger):

$$\Delta_{rating} = K \cdot M \cdot (S - E)$$

Where:
- $K$ = K-factor (20 regular, 4 postseason)
- $M$ = margin-of-victory multiplier:
  $$M = 1 + \min(M_{cap}, (\text{margin}/D)^2)$$
  with $D = 6$ and $M_{cap} = 2.5$
- $S$ = actual result (1.0 home win, 0.5 tie, 0.0 away win)
- $E$ = expected result for the team being updated

## Parameters (Frozen)

| Parameter | Value | Rationale |
| --- | --- | --- |
| `initial_rating` | 1500.0 | NFL-standard starting Elo |
| `k_factor_regular` | 20.0 | 538-style for football |
| `k_factor_postseason` | 4.0 | Less variance in small sample |
| `home_field_elo` | 48.0 | ≈3 points Pythagorean equivalent |
| `season_mean_reversion_fraction` | 1/3 | Standard 538 carryover |
| `mov_divisor` | 6.0 | FiveThirtyEight convention |
| `mov_cap` | 2.5 | Caps extreme blowouts |
| `prob_min` | 0.01 | Numerical safety |
| `prob_max` | 0.99 | Numerical safety |

## QB Adjustment

Because the Task 02 feature output records mostly `POSTGAME_ONLY_EVIDENCE`
(no confirmed pregame starter), the model defaults to `qb_adjustment = 0.0`
for every prediction. This is the conservative neutral approach documented
in Task 03A.

When `starter_certainty == CONFIRMED` and a QB pregame-EPA record is
present, the adjustment is:

$$q = \text{clamp}\left( \frac{n_{games}}{n_{games} + k} \cdot (E_{expected} - E_{prior}) \cdot \text{scale}, -q_{max}, q_{max} \right)$$

Where:
- $n_{games}$ = games played by the starter (shrinkage weight)
- $k$ = shrinkage constant (default 100)
- $E_{expected}$ = expected pregame EPA per play
- $E_{prior}$ = positional prior EPA per play
- `scale` = Elo points per EPA-per-play (default 10)
- $q_{max}$ = maximum absolute adjustment (default 50)

This is documented but **never triggered** in the current development run
because all 1,942 game predictions have `starter_certainty = UNKNOWN`.

## Tie Handling
A tie yields $S = 0.5$ for both teams, with no margin-of-victory
multiplier. The Elo update is symmetric.

## Neutral-Site Handling
When `neutral_site == True`, $HFA = 0$ and the probability is symmetric
in team Elos. Applied to all Super Bowls and international games.

## Season Carryover
Between seasons, every team's Elo is mean-reverted by
`season_mean_reversion_fraction` toward the league-wide mean rating at
that time. This stabilizes the system over long horizons.

## What This Model Does NOT Do
- No XGBoost
- No opponent-adjusted expected margin
- No stacker
- No calibration
- No sportsbook data
- No 2025 holdout access
- No Pinnacle / DK / FD comparison
- No CLV
- No deployment / frontend
