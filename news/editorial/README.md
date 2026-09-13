# NFL EDGE Daily News Editorial Handoff V1

This branch is an operational handoff bus between the VPS DeepHermes researcher and the ChatGPT editorial pass.

Branch: `ops/daily-news-editorial-v1`

## Roles

- **DeepHermes**: research only. Produces the governed `NFL_EDGE_DAILY_NEWS_RESEARCH_V1` packet.
- **ChatGPT editor**: writes the final `NFL_EDGE_DAILY_NEWS_V1` article from that packet.
- **VPS/Hermes publisher**: validates the finished article against the checked-in schema and source/evidence linkage, then atomically promotes it to the News runtime.

DeepHermes is not the final editorial writer on this branch.

## Paths

### Research inbox

`news/editorial/inbox/YYYY-MM-DDTHHMMSSZ-research.json`

The newest packet is also copied to:

`news/editorial/inbox/latest.json`

### Finished article outbox

`news/editorial/outbox/YYYY-MM-DDTHHMMSSZ-article.json`

The newest approved article is also copied to:

`news/editorial/outbox/latest.json`

## Research packet requirements

The inbox packet must be the exact governed packet that would otherwise be sent to the writer:

`NFL_EDGE_DAILY_NEWS_RESEARCH_V1`

It must include:
- external source evidence;
- current prospective card context;
- episode-specific Market Watch evidence;
- previous article/research context when available;
- generated timestamp;
- no secrets or credentials.

The research packet is evidence. Do not rewrite or "improve" it before committing.

## Editorial rules

The editor writes for casual/new NFL bettors by default. Do not address them as a special subgroup.

Sections have distinct jobs:

1. **What Matters Today** — concise football news, including meaningful injuries/QB status/weather.
2. **What It Means for NFL EDGE** — only what those facts change or do not change for the current card.
3. **The Fade** — always present. If no verified retail-vs-sharper divergence exists, say so and explain what movement would become actionable.
4. **Market Watch** — only observed card/price/Play Through changes from canonical prospective evidence. No opportunistic raw model/fair-price leakage.
5. **Today's Tip** — a standalone betting/app lesson. Never a summary of today's injury/news section.

Additional rules:
- Personality strong, evidence strict.
- Do not invent causal explanations for line movement.
- Do not call Circa action literal "sharp bettors".
- Do not blindly fade public action.
- Weather is checked every publication; if it is not actionable, say so briefly rather than silently pretending it was never checked.
- Every factual article item outside Today's Tip must cite packet evidence IDs.
- Article source URLs must come from cited packet evidence.
- No new recurring catchphrases beyond the approved Monday/Thursday checks.

## VPS publication

Hermes must:
1. fetch the latest outbox article from this branch;
2. verify its schema and evidence IDs against the paired inbox research packet;
3. reject stale, unsupported, or mismatched artifacts;
4. atomically promote only the verified article/research pair to `/var/lib/nfl-edge/news_v1/latest.json` and `research/latest.json`;
5. preserve last-good publication on failure.

This operational branch does not modify model, evaluator, selector, staking, sportsbook acquisition, canonical product, or prospective-tracking methodology.
