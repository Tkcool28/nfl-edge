from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_backend_systemd_uses_existing_entrypoint_and_bounded_restart() -> None:
    unit = _read("deploy/systemd/nfl-edge-backend.service")
    assert "WorkingDirectory=/root/nfl-edge" in unit
    assert "ExecStart=/root/nfl-edge/.venv/bin/python /root/nfl-edge/scripts/run_backend_v1.py" in unit
    assert "EnvironmentFile=/etc/nfl-edge/backend.env" in unit
    assert "Restart=on-failure" in unit
    assert "StartLimitBurst=5" in unit
    assert "ProtectSystem=strict" in unit
    assert (
        "ReadWritePaths=/var/lib/nfl-edge/backend /var/lib/nfl-edge/product_v1 "
        "/var/lib/nfl-edge/news_v1/editorial_inbox"
    ) in unit
    assert "run_2026_live_market_product_snapshot" not in unit
    assert "ODDS_API_KEY" not in unit


def test_production_env_keeps_state_outside_repo_and_api_loopback_only() -> None:
    env = _read("deploy/nfl-edge-backend.env.example")
    assert "NFL_EDGE_BACKEND_HOST=127.0.0.1" in env
    assert "NFL_EDGE_BACKEND_PORT=8769" in env
    assert "NFL_EDGE_DB_PATH=/var/lib/nfl-edge/backend/nfl_edge_users_v1.sqlite3" in env
    assert "NFL_EDGE_PRODUCT_DIR=/var/lib/nfl-edge/product_v1" in env
    assert "NFL_EDGE_DECISION_STATE_PATH=/root/nfl-edge/data/live/2026/entering_product_state_v1.json" in env
    assert "NFL_EDGE_COOKIE_SECURE=true" in env
    assert "NFL_EDGE_COOKIE_SAMESITE=lax" in env
    assert "NFL_EDGE_ALLOWED_ORIGIN=\n" in env
    assert "NFL_EDGE_ALLOWED_HOSTS=nfl.tkhermes.duckdns.org,localhost,127.0.0.1" in env
    assert "ODDS_API_KEY" not in env


def test_caddy_is_same_origin_and_routes_api_to_loopback() -> None:
    caddy = _read("deploy/caddy/nfl-edge.Caddyfile")
    assert "nfl.tkhermes.duckdns.org" in caddy
    assert "@api path /api/*" in caddy
    assert "reverse_proxy 127.0.0.1:8769" in caddy
    assert 'header Cache-Control "no-store"' in caddy
    assert "root * /srv/nfl-edge/frontend/current" in caddy
    assert "try_files {path} /index.html" in caddy
    assert "manifest.webmanifest" in caddy
    assert 'Content-Type "application/manifest+json"' in caddy


def test_frontend_activation_is_versioned_and_refuses_tracked_changes() -> None:
    script = _read("deploy/scripts/sync_frontend_v1.sh")
    assert 'sha="$(git -C "${repo_root}" rev-parse --verify HEAD)"' in script
    assert 'release_dir="${releases_dir}/${sha}"' in script
    assert "git -C \"${repo_root}\" diff --quiet" in script
    assert "git -C \"${repo_root}\" diff --cached --quiet" in script
    assert 'mv -Tf "${next_link}" "${current_link}"' in script
    assert "git clean" not in script


def test_deployment_contract_supersedes_obsolete_static_only_rule() -> None:
    contract = _read("docs/deployment_contract.md")
    deploy_readme = _read("deploy/README.md")
    assert "This contract supersedes the former static-only deployment rule." in contract
    assert "permanent FastAPI backend runtime" in deploy_readme
    assert "A permanent NFL backend service" not in contract
    assert "must not retain an NFL Python runtime" not in deploy_readme
    assert "HTTP requests must never trigger" in contract
    assert "/var/lib/nfl-edge/backend/nfl_edge_users_v1.sqlite3" in contract
    assert "/var/lib/nfl-edge/product_v1/latest.json" in contract


def test_runbook_preserves_zero_credit_deployment_target_and_acceptance_boundary() -> None:
    runbook = _read("docs/integrated_vps_deployment_v1.md")
    assert "provider requests: 0" in runbook
    assert "Odds API credits:  0" in runbook
    assert "Repository preparation alone does **not** earn that verdict." in runbook
    assert "Do not run `git clean`." in runbook
    assert "After acceptance, stop. Launch UX Polish is the next separate milestone" in runbook


def test_daily_news_runtime_is_isolated_and_waits_for_fresh_tracker() -> None:
    unit = _read("deploy/systemd/nfl-edge-daily-news.service")
    timer = _read("deploy/systemd/nfl-edge-daily-news.timer")
    env = _read("deploy/nfl-edge-news.env.example")
    backend_env = _read("deploy/nfl-edge-backend.env.example")

    assert "Requires=nfl-edge-prospective-persistence.service" in unit
    assert "After=network-online.target nfl-edge-prospective-persistence.service" in unit
    assert "ReadOnlyPaths=/root/nfl-edge /var/lib/nfl-edge/prospective_repo_v1" in unit
    assert "ExecStart=/root/nfl-edge/.venv/bin/python /root/nfl-edge/scripts/nfl_edge_daily_news_v1.py" in unit
    assert "ReadWritePaths=/var/lib/nfl-edge/news_v1" in unit
    assert "ODDS_API_KEY" not in unit
    assert "06:20:00 America/Denver" in timer
    assert "18:20:00 America/Denver" in timer
    assert "NFL_EDGE_NEWS_RUNTIME_ROOT=/var/lib/nfl-edge/news_v1" in env
    assert "NFL_EDGE_NEWS_EVIDENCE_ROOT=/var/lib/nfl-edge/prospective_repo_v1" in env
    assert "NFL_EDGE_NEWS_LATEST_PATH=/var/lib/nfl-edge/news_v1/latest.json" in backend_env
    assert (
        "NFL_EDGE_NEWS_EDITORIAL_INBOX_PATH=/var/lib/nfl-edge/news_v1/editorial_inbox/latest.json"
        in backend_env
    )
    assert "NFL_EDGE_NEWS_EDITORIAL_TOKEN=" in backend_env
    assert "ODDS_API_KEY" not in env


def test_editorial_publisher_is_a_separate_inactive_timer_contract() -> None:
    unit = _read("deploy/systemd/nfl-edge-news-editorial-publisher.service")
    timer = _read("deploy/systemd/nfl-edge-news-editorial-publisher.timer")
    old_timer = _read("deploy/systemd/nfl-edge-daily-news.timer")

    assert "ExecStart=/root/nfl-edge/.venv/bin/python /root/nfl-edge/scripts/publish_news_editorial_v1.py" in unit
    assert "ReadOnlyPaths=/root/nfl-edge" in unit
    assert "ReadWritePaths=/var/lib/nfl-edge/news_v1" in unit
    assert "06:35:00 America/Denver" in timer
    assert "18:35:00 America/Denver" in timer
    assert "nfl-edge-daily-news.service" in old_timer
    assert "nfl-edge-news-editorial-publisher.service" not in old_timer



def test_live_weekly_inputs_are_non_billable_and_precede_production() -> None:
    service = _read("deploy/systemd/nfl-edge-live-weekly-inputs.service")
    timer = _read("deploy/systemd/nfl-edge-live-weekly-inputs.timer")
    production = _read("deploy/systemd/nfl-edge-production-refresh.service")

    assert "materialize_live_weekly_inputs_v1.py" in service
    assert "ODDS_API_KEY" not in service
    assert "live_inputs_v1/2026" in service
    assert "00:01:00 UTC" in timer
    assert "12:01:00 UTC" in timer
    assert "Persistent=false" in timer
    assert "--schedule-root /var/lib/nfl-edge/live_inputs_v1/2026" in production
    assert "--evidence-root /var/lib/nfl-edge/live_inputs_v1/2026" in production


def test_production_refresh_can_acquire_live_input_lock_under_hardened_sandbox() -> None:
    """The settled-evidence reader opens <evidence-root>/.live-inputs.lock in
    'a+' mode (shared fcntl), which requires write access on the season
    evidence root. The production-refresh unit must grant read-write on exactly
    that governed lock directory -- not the whole live_inputs tree -- so a
    Week N refresh can consume the materialized weekly inputs under
    ProtectSystem=strict without weakening other sandboxing."""
    unit = _read("deploy/systemd/nfl-edge-production-refresh.service")
    assert "ProtectSystem=strict" in unit
    # The governed lock directory is the same season evidence root passed to
    # --evidence-root. Grant it, and only it, on the live-inputs tree.
    assert "/var/lib/nfl-edge/live_inputs_v1/2026" in unit
    assert "ReadWritePaths=/var/lib/nfl-edge/production_refresh_v1 " \
        "/var/lib/nfl-edge/product_v1 /var/lib/nfl-edge/prospective_card_log_v1 " \
        "/var/lib/nfl-edge/live_inputs_v1/2026" in unit
    # Least privilege: do NOT grant the whole live_inputs tree or its parent.
    assert "/var/lib/nfl-edge/live_inputs_v1" in unit  # present only via .../2026
    assert "ReadWritePaths=/var/lib/nfl-edge/live_inputs_v1 " not in " " + unit
    assert "live_inputs_v1/2026\n" in unit or "live_inputs_v1/2026 " in unit
    # No new broad-write paths or sandbox weakening.
    assert "ProtectHome=read-only" in unit
    assert "ProtectSystem=relaxed" not in unit
    assert "ReadWritePaths=/var/lib/nfl-edge " not in " " + unit
