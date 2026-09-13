# NFL EDGE Daily News Research Command V1

The research command is an external agent boundary. NFL EDGE sends canonical card context on stdin and expects one JSON object on stdout.

## Input

Schema: `NFL_EDGE_DAILY_NEWS_RESEARCH_REQUEST_V1`

It contains:
- `card_context` with latest and previous prospective publication IDs/timestamps;
- current recommendation episodes and previous/latest observations for real movement comparison;
- `previous_article` when a prior morning/evening brief exists;
- `previous_research` when the prior governed research packet exists;
- explicit comparison instructions;
- card-context provider_calls = 0.

Use the previous article/research to identify verified changes since the last brief. Do not reconstruct a prior state from memory when the prior packet is available.

## Output

Schema: `NFL_EDGE_DAILY_NEWS_EXTERNAL_RESEARCH_V1`

```json
{
  "schema_version": "NFL_EDGE_DAILY_NEWS_EXTERNAL_RESEARCH_V1",
  "evidence": [
    {
      "evidence_id": "injury:team-player-2026-09-12",
      "category": "injury",
      "verification": "OFFICIAL",
      "fact": "Plain factual statement.",
      "interpretation": "What it could mean, without pretending causation is proven.",
      "app_guidance": "How a user should apply this information inside NFL EDGE.",
      "sources": [
        {
          "label": "NFL",
          "url": "https://...",
          "published_at_utc": "2026-09-12T18:00:00Z"
        }
      ]
    }
  ]
}
```

## Research priorities

1. Official NFL/team injury, transaction, inactive, and QB status.
2. Credible corroboration/reporting where official information is incomplete.
3. Kickoff-window weather from official weather services when possible.
4. DraftKings/public betting context and Circa/VSiN sharper-market context for The Fade.
5. Other verified NFL developments that actually matter to the current slate.
6. Current power-ranking/consensus context only when useful and deduplicated by original publisher.

For U.S. stadium weather prefer NWS/NOAA. International games need an appropriate host-country official or licensed source.

Reporter social feeds are discovery/corroboration, not automatic official truth.

## The Fade evidence rule

Never label Circa splits as literal "sharp bettors" or claim that public action caused a line move unless evidence supports it.

Safe evidence distinguishes:
- observed DraftKings/public split;
- observed Circa split;
- observed price/line movement;
- interpretation of what the divergence could mean.

If there is no meaningful verified divergence, return no Fade evidence rather than forcing one.

## Zero Odds API rule

This command must not make additional paid Odds API calls solely for News. Use existing NFL EDGE market/card evidence and zero-cost/public sources.
