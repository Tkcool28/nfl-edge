# NFL EDGE Daily News V1

NFL EDGE Daily News is an editorial layer downstream of the betting product.

## Editorial rule

**Personality strong, evidence strict.**

Write for football fans who bet, including casual and newer bettors. Prefer plain football and betting language over analyst or quant jargon. Explain how each important item could affect the user's use of NFL EDGE without turning news, betting splits, or market movement into an automatic bet signal.

New recurring catchphrases must be approved before publication.

## Runtime contract

The backend reads the latest published brief from:

- default: `data/runtime/news_v1/latest.json`
- production override: `NFL_EDGE_NEWS_LATEST_PATH`

Production may point this at `/var/lib/nfl-edge/news_v1/latest.json`.

News is independent of canonical product generation. A missing or malformed news artifact fails only `GET /api/v1/news/latest` and must never block the Board, product refresh, market acquisition, model scoring, selectors, staking, or wager logging.

## Schema

Top-level fields:

- `schema_version`: exactly `NFL_EDGE_DAILY_NEWS_V1`
- `published_at_utc`: ISO-8601 UTC timestamp
- `edition`: short display label such as `Morning Brief` or `Saturday Night Check`
- `title`: article title
- `dek`: optional short intro
- `sections`: ordered list of article sections

Each section supports:

- `id`
- `title`
- `icon`
- `items`

Each item supports:

- `headline`
- `paragraphs`: ordered plain-text paragraphs
- `bullets`: optional plain-text bullets
- `takeaway`: optional highlighted plain-text usage guidance
- `sources`: optional list of `{"label": "...", "url": "https://..."}`

The frontend escapes all editorial text and only renders http/https source links.

## Intended section order

1. What Matters Today
2. What It Means for NFL EDGE
3. The Fade
4. Market Watch
5. Today's Tip

Sections may be omitted when there is nothing useful to say.

## The Fade

The Fade is a decision-context tool, not a standalone pick.

A good Fade item should:

1. identify the retail-vs-sharper-market split;
2. explain what the split could mean in plain language;
3. explain what sharper bettors are doing when relevant;
4. say what line or price movement to watch next;
5. explain how the user can apply that information inside NFL EDGE, including whether waiting could improve a price or whether Play Through is being approached or crossed.

Do not tell users to blindly fade the public, blindly follow Circa, or bet against the model.
