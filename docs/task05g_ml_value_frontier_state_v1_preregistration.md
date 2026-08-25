# Task05G ML Value Frontier State V1 — Preregistration

Status: preregistered before implementation/results on this branch.

Purpose: keep the corrected frontier-aligned trust signal, but add an earlier AMBER response so a deteriorating ML Value frontier can lose priority before the stronger RED evidence threshold is reached.

No Task05F evaluator, football model, Task05E evidence, production policy, historical data, HHR/Balanced logic, or sealed 2025 data changes.

## Chronology

- 2020–2022: development replay.
- 2023–2024: exposed retrospective stress replay only.
- 2025: sealed/prohibited.
- Trust at each block uses only strictly prior same-season settled frontier observations.

## Frozen frontier trust

Use exactly Frontier Trust V1:

- one top-ranked ML Value frontier observation per settled prior block maximum;
- season reset trust 0.50;
- pseudo-count 8;
- trust formula unchanged;
- frontier Value eligibility/ranking unchanged.

## States

### GREEN

Default state.

- Conditions: fewer than 3 prior frontier observations, or trust >= 0.50.
- Selection: use frontier-trust dynamic ranking exactly as F1.

### AMBER

- Conditions: at least 3 prior frontier observations and trust < 0.50, but RED is not active.
- Selection behavior: if at least one valid spread Value candidate exists in the block, choose the highest-ranked spread Value candidate and do not allow ML to outrank it.
- If no valid spread Value candidate exists, ML remains eligible and the normal dynamic ranking applies.
- AMBER therefore changes market priority but does not create a forced no-play.

### RED

- Conditions: at least 8 prior frontier observations and trust < 0.25.
- Selection behavior: ML is ineligible for the Value headline; choose the highest-ranked spread Value candidate if one exists, otherwise PASS/no-play.
- ML automatically returns if strictly prior evidence raises trust above the RED threshold.

## Variants

- S0: frozen Value V2 baseline.
- S1: frontier dynamic ranking only (equivalent to F1).
- S2: GREEN/AMBER/RED frontier state machine above.

No additional thresholds or states may be added after results.

## Coverage guard

S2 is flagged `COVERAGE_COLLAPSE` if play count falls below 75% of S0 in either 2020–2022 or exposed 2023–2024 stress replay.

## Required diagnostics

For S0/S1/S2 report:

- plays, coverage, hit rate, ROI;
- ML/spread counts and ROI;
- season-by-season results;
- max losing streak;
- AMBER and RED block counts by season;
- number of ML headlines displaced to spread in AMBER;
- RED no-play count;
- first AMBER and first RED block each season;
- trust state at those crossings.

## Interpretation

The desired behavior is not to predict a regime break before evidence exists. It is to:

1. preserve profitable ML frontier behavior in 2020–2022, especially 2022;
2. react earlier than the RED-only frontier system during the 2023 collapse;
3. preserve useful play coverage;
4. avoid treating already-exposed 2023–2024 as fresh confirmation.

2025 remains sealed for eventual true validation.