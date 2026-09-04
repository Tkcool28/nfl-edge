# NFL EDGE Frontend V1

Mobile-first production frontend for the existing FastAPI backend. It preserves the staged `NFL_Front` visual language while removing mock/static product authority.

## Authority boundary
The browser renders backend state and collects user input. It does not calculate model/trust probabilities, evaluator verdicts, lane eligibility, recommended units, bankroll staking, slate caps, duplicate suppression, Play Through, Value At, exact-offer recommendations, roof averages, or market acquisition. API calls use same-origin `/api/v1/...` paths; `globalThis.NFL_EDGE_API_BASE` is development-only. Auth remains the backend HttpOnly cookie. Local storage is presentation-only.

## Staging bundle audit
- `styles.css` is the retained visual foundation.
- `index.html` concepts are normalized into a single mobile app shell.
- staged `app.js` is not business authority because it contained mock bankroll/staking/evaluation behavior.
- `data/latest.json` is retired as product authority.
- `review.html` and `snapshot.html` are retired; their useful detail concepts are backend-driven views.

## PWA
`manifest.webmanifest` uses standalone mode with 192/512 maskable-capable icons. `sw.js` caches only the app shell. `/api/` is always network/no-store and never replayed from Cache Storage. Offline mode never presents a cached recommendation as current.

The directory is self-contained for Sep 7 same-origin deployment and has no runtime dependency on `NFL_Front`.
