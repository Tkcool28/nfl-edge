# NFL EDGE Daily News V1 — Production Activation Runbook

This runbook begins only after the Daily News production-pipeline PR is merged.

## Goal

Activate the already-merged app reader and governed News pipeline on the production VPS.

Do not modify model methodology, selectors, staking, market acquisition, canonical product generation, wager logic, or the prospective tracking contract.

Do not make additional paid Odds API requests for News.

Do not use `git clean`.

## 1. Sync production repository

Production repo: `/root/nfl-edge`.

Verify tracked state before sync. Preserve unrelated untracked runtime evidence. Fetch and fast-forward to the exact merged `main` commit.

Confirm:
- `news/README.md`
- `news/RESEARCH_COMMAND_V1.md`
- `news/WRITER_COMMAND_V1.md`
- `scripts/nfl_edge_daily_news_v1.py`
- `deploy/systemd/nfl-edge-daily-news.service`
- `deploy/systemd/nfl-edge-daily-news.timer`

## 2. Runtime directories

Create:

```text
/var/lib/nfl-edge/news_v1/
/var/lib/nfl-edge/news_v1/research/
/var/lib/nfl-edge/news_v1/archive/
```

The News service is the only writer. The backend is read-only against `latest.json`.

## 3. Backend path

Ensure `/etc/nfl-edge/backend.env` contains:

```text
NFL_EDGE_NEWS_LATEST_PATH=/var/lib/nfl-edge/news_v1/latest.json
```

Restart only `nfl-edge-backend.service` after the repo sync/env change and verify:

```text
GET /api/v1/health
GET /api/v1/product/latest
```

A missing News file may return 404 from `GET /api/v1/news/latest`; that must not affect the Board/product endpoints.

## 4. Research + writer wrappers

Install two executable wrappers:

```text
/usr/local/bin/nfl-edge-news-research
/usr/local/bin/nfl-edge-news-writer
```

They must obey the checked-in JSON contracts.

Research:
- stdin: `NFL_EDGE_DAILY_NEWS_CARD_CONTEXT_V1`
- stdout: `NFL_EDGE_DAILY_NEWS_EXTERNAL_RESEARCH_V1`

Writer:
- stdin: `NFL_EDGE_DAILY_NEWS_RESEARCH_V1`
- stdout: `NFL_EDGE_DAILY_NEWS_V1`

The wrappers must emit JSON only on stdout. Diagnostics belong on stderr.

Research priorities:
- official NFL/team injury/QB/transaction/inactive information;
- credible reporter/context corroboration;
- official kickoff-window weather where possible;
- DraftKings/public vs Circa/VSiN context for The Fade;
- other verified slate-relevant NFL developments.

The writer must preserve:
- “Personality strong, evidence strict.”
- casual/new-bettor language;
- five-section order;
- The Fade usage explanation;
- evidence IDs and source URLs from the packet only.

No credentials should appear in command-line arguments.

## 5. News environment

Install `deploy/nfl-edge-news.env.example` as `/etc/nfl-edge/news.env` with mode 0600 and set:

```text
NFL_EDGE_NEWS_RUNTIME_ROOT=/var/lib/nfl-edge/news_v1
NFL_EDGE_NEWS_EVIDENCE_ROOT=/var/lib/nfl-edge/prospective_repo_v1
NFL_EDGE_NEWS_RESEARCH_COMMAND=/usr/local/bin/nfl-edge-news-research
NFL_EDGE_NEWS_WRITER_COMMAND=/usr/local/bin/nfl-edge-news-writer
```

## 6. Install units

Copy:

```text
deploy/systemd/nfl-edge-daily-news.service -> /etc/systemd/system/
deploy/systemd/nfl-edge-daily-news.timer   -> /etc/systemd/system/
```

Run:

```bash
systemctl daemon-reload
systemctl cat nfl-edge-daily-news.service
systemctl cat nfl-edge-daily-news.timer
```

Verify the service:
- Requires and runs after `nfl-edge-prospective-persistence.service`
- reads `/root/nfl-edge` and `/var/lib/nfl-edge/prospective_repo_v1`
- writes only `/var/lib/nfl-edge/news_v1`

Verify timer windows:
- 06:20 America/Denver
- 18:20 America/Denver

## 7. First controlled publication

Before enabling the timer:

```bash
systemctl start nfl-edge-daily-news.service
systemctl status nfl-edge-daily-news.service --no-pager
journalctl -u nfl-edge-daily-news.service -n 100 --no-pager
```

A successful run must report `PUBLISHED`.

Verify:
- `/var/lib/nfl-edge/news_v1/research/latest.json`
- `/var/lib/nfl-edge/news_v1/candidate.json`
- `/var/lib/nfl-edge/news_v1/latest.json`
- one immutable file under `archive/`

Then verify:

```bash
curl -fsS http://127.0.0.1:8769/api/v1/news/latest | python3 -m json.tool
```

Review the actual article before enabling the timer.

## 8. Failure isolation acceptance

Required:
- Board/product API remains healthy if News fails.
- A failed News run leaves the previous `latest.json` byte-for-byte unchanged.
- no model/product files change;
- no sportsbook acquisition command runs;
- Odds API credits consumed by News: 0.

## 9. Enable cadence

Only after the controlled article is approved:

```bash
systemctl enable --now nfl-edge-daily-news.timer
systemctl list-timers --all | grep nfl-edge-daily-news
```

Expected ongoing cadence:
- Saturday-night/evening checks give the user a pre-Sunday read.
- Sunday morning shows verified overnight changes.
- ordinary 06:20/18:20 Denver checks continue without forcing content on quiet slates.

## Acceptance verdict

Use:

`NFL_EDGE_DAILY_NEWS_V1_LIVE`

only after:
1. merged code is deployed;
2. a controlled real article publishes successfully;
3. the API serves it;
4. the app News view displays it;
5. last-good failure isolation is proven;
6. the timer is enabled and armed.
