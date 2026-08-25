# Task05G HHR Market-Price Corroboration Audit Plan

Status: frozen diagnostic plan. No selector or production-policy change is authorized by this document.

## Question

For current HHR moneyline headlines, distinguish:

1. a **genuine heavy favorite**, where the sharp two-sided market itself assigns high win probability; from
2. a **retail overjuiced favorite**, where the best available DraftKings/FanDuel price requires materially more win probability than the Pinnacle no-vig market implies.

The audit also tests whether current HHR max-confidence selection systematically prefers candidates whose model confidence is much stronger than market corroboration.

## Frozen upstream stack

- Task05F evaluator and exact-offer shopping unchanged.
- Model Confidence V2 ML calibration unchanged.
- Spread Confidence V3 unchanged.
- HHR eligibility and ordering unchanged.
- ML Headline Trust V1 remains diagnostic only and is not used to select this audit population.
- 2025 remains sealed and prohibited.

Periods:

- 2020-2022: development diagnostic.
- 2023-2024: already-exposed locked diagnostic.
- 2025: sealed.

## Exact fields

For each exact-shopped HHR-eligible moneyline candidate:

- `model_confidence_probability`: existing ML confidence.
- `pinnacle_anchor_probability`: raw selected-side Pinnacle two-sided proportional no-vig probability from Task05F.
- `break_even_probability`: implied probability required by the best actionable DK/FD price.
- `american_odds`: best actionable DK/FD moneyline price.
- `raw_qbelo_probability_selected`, `raw_xgb_probability_selected`: constituent football-model probabilities.

Derived quantities:

- `retail_juice_premium = break_even_probability - pinnacle_anchor_probability`.
  - Positive means the retail book requires a higher hit rate than the Pinnacle no-vig benchmark.
- `model_minus_pinnacle = model_confidence_probability - pinnacle_anchor_probability`.
  - Positive means the model-confidence layer is more bullish than the sharp market.
- `qb_xgb_abs_disagreement = abs(raw_qbelo_probability_selected - raw_xgb_probability_selected)`.

## Frozen descriptive definitions

These labels are fixed before outcomes are inspected by this audit.

### Sharp-market favorite strength

Pinnacle no-vig buckets:

- `<55%`
- `55-60%`
- `60-65%`
- `65-70%`
- `70-75%`
- `>=75%`

For the audit's descriptive quadrant only:

- **genuine heavy favorite** = Pinnacle no-vig probability >= 65%.

### Retail juice premium

`break_even - Pinnacle no-vig` buckets:

- `<=0pp`
- `0-1pp`
- `1-2.5pp`
- `2.5-5pp`
- `>5pp`

For the descriptive quadrant only:

- **material retail overjuice** = retail juice premium >= 2.5 percentage points.

### Model-vs-market gap

`model confidence - Pinnacle no-vig` buckets:

- `<=0pp`
- `0-5pp`
- `5-10pp`
- `10-15pp`
- `>15pp`

### Actionable price

American-odds buckets:

- `<=-250`
- `-249..-201`
- `-200..-151`
- `-150..-111`
- `-110..+100`
- `+101..+200`

## Frozen analyses

For both periods, report:

1. all exact-shopped HHR-eligible ML candidates;
2. actual current HHR ML headlines;
3. ML-only rank 1, rank 2, and rank 3 under the frozen HHR ordering;
4. calibration/hit/ROI summaries by Pinnacle-strength bucket;
5. summaries by retail-juice-premium bucket;
6. summaries by model-minus-Pinnacle bucket;
7. summaries by actionable-odds bucket;
8. the fixed 2x2 descriptive quadrant:
   - genuine heavy + not materially overjuiced;
   - genuine heavy + materially overjuiced;
   - not genuine heavy + not materially overjuiced;
   - not genuine heavy + materially overjuiced;
9. selected-vs-rank-2 differences in Pinnacle probability, retail premium, model-minus-market gap, constituent disagreement, odds, hit rate, and ROI.

## Interpretation constraints

- This is diagnostic only.
- No bucket boundary may be changed after outcome output.
- No bucket or quadrant may be converted directly into a production threshold from this audit.
- No attractive 2023-2024 pattern may be promoted; those outcomes are already exposed.
- A later selector experiment, if justified, must be separately preregistered and ranking-only first with an explicit coverage-parity guardrail.
- Do not modify Task05F, football models, ML calibration, Spread V3, HHR eligibility, units, bankroll policy, or Play Through.
- Do not open 2025.
