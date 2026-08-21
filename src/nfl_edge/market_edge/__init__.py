"""Task 05E Market Edge — permanent deterministic scorer/replay.

Repo-native implementation of the frozen Market Edge preregistration
(fingerprint d19534094...2e5c) with the five mechanical corrections:

  1. AVG exists only when BOTH QB-Elo and XGBoost predictions exist (no fallback)
  2. spread shopping: selected-side best number first, then better price, then
     deterministic tie-break
  3. candidate boundaries use exact raw numeric values (no rounded/report bins)
  4. the one-row ledger is authoritative for all grading and reporting
  5. deterministic same-side W/L/P grading from game_id/final score, actual
     DK/FD actionable return prices, Pinnacle benchmark only.

The SAME scoring code path runs separately for discovery (2020-2022) and
confirmation (2023-2024); 2025 is sealed and never read.
"""