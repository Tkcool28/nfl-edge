from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from nfl_edge.operations import production_refresh_v1 as refresh


class _FreshSleeper:
    snapshot_id = "sleeper-test-snapshot"
    observed_at_utc = "2026-09-09T00:00:00Z"
    freshness_state = "FRESH"
    source_warning_state = None

    @staticmethod
    def freshness_contract() -> dict[str, object]:
        return {"state": "FRESH"}


def _config(tmp_path: Path, *, live: bool = True) -> refresh.RefreshConfig:
    response = None if live else tmp_path / "saved-response.json"
    if response is not None:
        response.write_text("[]", encoding="utf-8")
    return refresh.RefreshConfig(
        repository_root=tmp_path,
        run_root=tmp_path / "runs",
        publication_dir=tmp_path / "publication",
        prediction_as_of_utc="2026-09-09T00:05:00Z",
        live=live,
        market_response=response,
    )


def _wire_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, calls: list[str]) -> None:
    monkeypatch.setattr(refresh, "_validate_sleeper", lambda config: calls.append("sleeper") or _FreshSleeper())
    monkeypatch.setattr(refresh, "load_overrides", lambda path: {})
    monkeypatch.setattr(refresh, "SleeperExpectedQBResolver", lambda source, overrides: object())
    monkeypatch.setattr(
        refresh,
        "score_week1",
        lambda **kwargs: calls.append("score") or {"games": [{"id": "g"}], "snapshot_sha256": "a" * 64},
    )
    monkeypatch.setattr(refresh, "canonical_snapshot_bytes", lambda value: b"football")
    monkeypatch.setattr(
        refresh, "_validate_football", lambda path: {"games": [{"id": "g"}], "snapshot_sha256": "a" * 64}
    )
    monkeypatch.setattr(refresh, "load_week1_schedule", lambda path: {"season": 2026, "week": 1, "games": [{}]})
    monkeypatch.setattr(
        refresh,
        "acquire_live_response",
        lambda **kwargs: (
            calls.append("provider")
            or SimpleNamespace(response_path=tmp_path / "raw.json", metadata_path=tmp_path / "raw.meta.json")
        ),
    )
    (tmp_path / "raw.json").write_text("[]", encoding="utf-8")
    (tmp_path / "raw.meta.json").write_text("{}", encoding="utf-8")
    metadata = {
        "acquired_at_utc": "2026-09-09T00:05:00Z",
        "response_sha256": "b" * 64,
        "credits_consumed": 3,
        "credits_remaining": 97,
    }
    monkeypatch.setattr(refresh, "load_capture", lambda *args, **kwargs: ([], metadata))
    market = {"snapshot_version": "market-test", "snapshot_sha256": "c" * 64}
    monkeypatch.setattr(refresh, "normalize_market_snapshot", lambda **kwargs: calls.append("normalize") or market)
    monkeypatch.setattr(refresh, "market_snapshot_bytes", lambda market: b"market")
    monkeypatch.setattr(refresh, "load_entering_2026_product_state", lambda path: {})
    product = {"product_version": "product-test"}
    monkeypatch.setattr(
        refresh, "build_product_snapshot", lambda **kwargs: calls.append("materialize") or (product, {"proof": "ok"})
    )
    monkeypatch.setattr(refresh, "product_snapshot_bytes", lambda product: b"product")
    monkeypatch.setattr(refresh, "validate_product_snapshot", lambda product: product)

    class Store:
        def __init__(self, root: Path) -> None:
            self.root = root

        def publish(self, product: dict[str, object]) -> Path:
            calls.append("publish")
            path = self.root / "product-test.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")
            return path

        def load_latest(self, *, required: bool) -> dict[str, object]:
            return product

    monkeypatch.setattr(refresh, "ProductStore", Store)


def test_success_orders_stages_and_writes_secret_safe_artifacts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []
    _wire_success(monkeypatch, tmp_path, calls)

    outcome, summary = refresh.run_refresh(_config(tmp_path))

    assert outcome is refresh.RefreshOutcome.SUCCESS
    assert calls == ["sleeper", "score", "provider", "normalize", "materialize", "materialize", "publish"]
    assert summary["provider_request_count"] == 1
    status = json.loads((tmp_path / "runs" / "latest-status.json").read_text())
    assert status["outcome"] == "SUCCESS"
    assert "ODDS_API_KEY" not in json.dumps(status)


def test_saved_response_replay_never_calls_provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[str] = []
    _wire_success(monkeypatch, tmp_path, calls)

    outcome, summary = refresh.run_refresh(_config(tmp_path, live=False))

    assert outcome is refresh.RefreshOutcome.SUCCESS
    assert "provider" not in calls
    assert summary["provider_request_count"] == 0


def test_sleeper_failure_prevents_scoring_and_provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[str] = []
    monkeypatch.setattr(refresh, "_validate_sleeper", lambda config: (_ for _ in ()).throw(RuntimeError("stale")))
    monkeypatch.setattr(refresh, "score_week1", lambda **kwargs: calls.append("score"))
    monkeypatch.setattr(refresh, "acquire_live_response", lambda **kwargs: calls.append("provider"))

    outcome, summary = refresh.run_refresh(_config(tmp_path))

    assert outcome is refresh.RefreshOutcome.SLEEPER_NOT_READY
    assert calls == []
    assert summary["provider_request_count"] == 0


def test_scoring_failure_prevents_provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[str] = []
    monkeypatch.setattr(refresh, "_validate_sleeper", lambda config: _FreshSleeper())
    monkeypatch.setattr(refresh, "load_overrides", lambda path: {})
    monkeypatch.setattr(refresh, "SleeperExpectedQBResolver", lambda source, overrides: object())
    monkeypatch.setattr(refresh, "score_week1", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("score failed")))
    monkeypatch.setattr(refresh, "acquire_live_response", lambda **kwargs: calls.append("provider"))

    outcome, summary = refresh.run_refresh(_config(tmp_path))

    assert outcome is refresh.RefreshOutcome.SCORING_FAILED
    assert calls == []
    assert summary["provider_request_count"] == 0


def test_provider_failure_is_one_attempt_and_never_publishes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[str] = []
    _wire_success(monkeypatch, tmp_path, calls)
    monkeypatch.setattr(
        refresh,
        "acquire_live_response",
        lambda **kwargs: calls.append("provider") or (_ for _ in ()).throw(RuntimeError("HTTP 500")),
    )

    outcome, summary = refresh.run_refresh(_config(tmp_path))

    assert outcome is refresh.RefreshOutcome.MARKET_ACQUISITION_FAILED
    assert calls.count("provider") == 1
    assert "publish" not in calls
    assert summary["provider_request_count"] == 1


def test_normalization_failure_uses_saved_response_without_reacquiring(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []
    _wire_success(monkeypatch, tmp_path, calls)
    monkeypatch.setattr(
        refresh, "normalize_market_snapshot", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("bad capture"))
    )

    outcome, _ = refresh.run_refresh(_config(tmp_path))

    assert outcome is refresh.RefreshOutcome.MARKET_NORMALIZATION_FAILED
    assert calls.count("provider") == 1
    assert "publish" not in calls


def test_lock_prevents_overlapping_provider_call(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[str] = []
    _wire_success(monkeypatch, tmp_path, calls)
    config = _config(tmp_path)

    with refresh._exclusive_lock(config.run_root):
        outcome, summary = refresh.run_refresh(config)

    assert outcome is refresh.RefreshOutcome.LOCKED
    assert summary["provider_request_count"] == 0
    assert calls == []


def test_replay_metadata_and_error_messages_are_secret_redacted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []
    _wire_success(monkeypatch, tmp_path, calls)
    saved = tmp_path / "saved-response.json"
    meta = tmp_path / "saved-response.meta.json"
    meta.write_text(
        json.dumps(
            {
                "acquired_at_utc": "2026-09-09T00:05:00Z",
                "response_sha256": "b" * 64,
                "apiKey": "super-secret-key",
                "Authorization": "Bearer abc123",
                "note": "api_key=abcd1234",
                "nested": {"secret_token": "zzz"},
            }
        ),
        encoding="utf-8",
    )

    def capture(*args, **kwargs):
        events = json.loads(Path(args[0] if args else kwargs["response_path"]).read_text()) if False else []
        metadata = json.loads(meta.read_text())
        metadata["acquired_at_utc"] = "2026-09-09T00:05:00Z"
        return events, dict(metadata)

    monkeypatch.setattr(refresh, "load_capture", capture)
    monkeypatch.setattr(
        refresh,
        "normalize_market_snapshot",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("request failed with api_key=sk-live-9999")),
    )

    outcome, summary = refresh.run_refresh(_config(tmp_path, live=False))

    assert outcome is refresh.RefreshOutcome.MARKET_NORMALIZATION_FAILED
    persisted = json.loads((tmp_path / "runs" / "latest-status.json").read_text())
    text = json.dumps(persisted)
    assert "super-secret-key" not in text
    assert "Bearer abc123" not in text
    assert "sk-live-9999" not in text
    assert "[REDACTED]" in text
    run_dirs = sorted((tmp_path / "runs").glob("refresh-*"))
    meta_copy = json.loads((run_dirs[-1] / "raw" / "saved-response.meta.json").read_text())
    assert meta_copy["apiKey"] == "[REDACTED]"
    assert meta_copy["Authorization"] == "[REDACTED]"
    assert meta_copy["nested"]["secret_token"] == "[REDACTED]"
    assert "abcd1234" not in meta_copy["note"]


def test_replay_preserves_capture_timestamp_regardless_of_cli_as_of(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []
    _wire_success(monkeypatch, tmp_path, calls)
    meta = tmp_path / "saved-response.meta.json"
    meta.write_text(json.dumps({"acquired_at_utc": "2026-09-08T23:00:00Z", "response_sha256": "b" * 64}), encoding="utf-8")

    captured: dict[str, object] = {}

    def capture(*args, **kwargs):
        metadata = json.loads(meta.read_text())
        # Mimic the real load_capture: the explicit acquired_at_utc kwarg
        # overrides the saved metadata value.
        metadata["acquired_at_utc"] = str(kwargs.get("acquired_at_utc") or metadata["acquired_at_utc"])
        return [], dict(metadata)

    monkeypatch.setattr(refresh, "load_capture", capture)

    def normalize(**kwargs):
        captured["acquired_at_utc"] = kwargs["acquired_at_utc"]
        return {"snapshot_version": "market-test", "snapshot_sha256": "c" * 64}

    monkeypatch.setattr(refresh, "normalize_market_snapshot", normalize)

    config = _config(tmp_path, live=False)
    config = refresh.RefreshConfig(
        repository_root=config.repository_root,
        run_root=config.run_root,
        publication_dir=config.publication_dir,
        prediction_as_of_utc="2026-09-09T12:00:00Z",
        live=False,
        market_response=config.market_response,
        market_metadata=None,
    )
    outcome, summary = refresh.run_refresh(config)

    assert outcome is refresh.RefreshOutcome.SUCCESS
    # The CLI as-of must NOT override the saved capture timestamp.
    assert captured["acquired_at_utc"] == "2026-09-08T23:00:00Z"


def test_same_second_rerun_allocates_unique_run_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []
    _wire_success(monkeypatch, tmp_path, calls)

    first_id = refresh._run_id(refresh._utc_now())
    (tmp_path / "runs" / first_id).mkdir(parents=True)  # simulate same-second predecessor

    outcome, summary = refresh.run_refresh(_config(tmp_path))

    assert outcome is refresh.RefreshOutcome.SUCCESS
    assert summary["run_id"] != first_id
    assert (tmp_path / "runs" / summary["run_id"]).is_dir()


def test_same_second_pre_provider_failure_still_writes_truthful_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    first_id = refresh._run_id(refresh._utc_now())
    (tmp_path / "runs" / first_id).mkdir(parents=True)
    monkeypatch.setattr(refresh, "_validate_sleeper", lambda config: (_ for _ in ()).throw(RuntimeError("stale")))

    outcome, summary = refresh.run_refresh(_config(tmp_path))

    assert outcome is refresh.RefreshOutcome.SLEEPER_NOT_READY
    assert summary["run_id"] != first_id
    status = json.loads((tmp_path / "runs" / "latest-status.json").read_text())
    assert status["outcome"] == "SLEEPER_NOT_READY"


def test_systemd_contract_is_billable_safe() -> None:
    root = Path(__file__).resolve().parents[2]
    service = (root / "deploy/systemd/nfl-edge-production-refresh.service").read_text()
    timer = (root / "deploy/systemd/nfl-edge-production-refresh.timer").read_text()

    assert "Type=oneshot" in service
    assert "EnvironmentFile=/etc/nfl-edge/refresh.env" in service
    assert "ODDS_API_KEY=" not in service
    assert "Restart=no" in service
    assert "systemctl restart" not in service
    assert "Persistent=false" in timer
    assert "00:05:00 UTC" in timer
    assert "12:05:00 UTC" in timer
