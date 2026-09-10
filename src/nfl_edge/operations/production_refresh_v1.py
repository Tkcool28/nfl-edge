"""Bounded twice-daily production refresh orchestration.

This module intentionally composes existing scoring, market, product, and
publication contracts. It owns only ordering, locking, forensic artifacts, and
truthful terminal status; it does not implement model methodology.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

import re

from nfl_edge.backend.publication import ProductStore
from nfl_edge.contracts.live_product_v1 import validate_product_snapshot
from nfl_edge.live.markets_2026 import (
    acquire_live_response,
    load_capture,
    market_snapshot_bytes,
    normalize_market_snapshot,
)
from nfl_edge.live.product_2026 import build_product_snapshot, product_snapshot_bytes
from nfl_edge.live.product_state_2026 import load_entering_2026_product_state
from nfl_edge.live.scorer_2026 import canonical_snapshot_bytes, football_snapshot_hash, score_week1
from nfl_edge.live.sleeper_qb import DEFAULT_OVERRIDES, SleeperExpectedQBResolver, SleeperQBSource, load_overrides
from nfl_edge.live.week1_2026 import load_week1_schedule
from nfl_edge.prospective.runtime_v1 import capture_published_product


class RefreshOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    LOCKED = "LOCKED"
    SLEEPER_NOT_READY = "SLEEPER_NOT_READY"
    SCORING_FAILED = "SCORING_FAILED"
    MARKET_ACQUISITION_FAILED = "MARKET_ACQUISITION_FAILED"
    MARKET_NORMALIZATION_FAILED = "MARKET_NORMALIZATION_FAILED"
    MATERIALIZATION_FAILED = "MATERIALIZATION_FAILED"
    PUBLICATION_FAILED = "PUBLICATION_FAILED"


EXIT_CODES = {
    RefreshOutcome.SUCCESS: 0,
    RefreshOutcome.LOCKED: 75,
    RefreshOutcome.SLEEPER_NOT_READY: 20,
    RefreshOutcome.SCORING_FAILED: 21,
    RefreshOutcome.MARKET_ACQUISITION_FAILED: 22,
    RefreshOutcome.MARKET_NORMALIZATION_FAILED: 23,
    RefreshOutcome.MATERIALIZATION_FAILED: 24,
    RefreshOutcome.PUBLICATION_FAILED: 25,
}


class RefreshLockedError(RuntimeError):
    """Raised when another production refresh owns the exclusive run lock."""


@dataclass(frozen=True)
class RefreshConfig:
    repository_root: Path
    run_root: Path
    publication_dir: Path
    prediction_as_of_utc: str
    live: bool
    market_response: Path | None = None
    market_metadata: Path | None = None
    prospective_dir: Path | None = None


def _utc_now() -> str:
    now = datetime.now(timezone.utc)
    return now.isoformat(timespec="microseconds").replace("+00:00", "Z")


_SECRET_KEY_RE = re.compile(r"(api[-_]?key|authorization|token|secret|password|credential)", re.IGNORECASE)
_SECRET_TEXT_RE = re.compile(
    r"((?:api[-_]?key|authorization|token|secret|password|credential)[\"']?\s*[=:]\s*)(?:\S+)",
    re.IGNORECASE,
)
_REDACTED = "[REDACTED]"


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: (_REDACTED if _SECRET_KEY_RE.search(str(key)) else _redact_value(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, str):
        return _SECRET_TEXT_RE.sub(lambda match: match.group(1) + _REDACTED, value)
    return value


def _redact_error(error: BaseException | None) -> str | None:
    if error is None:
        return None
    return _SECRET_TEXT_RE.sub(lambda match: match.group(1) + _REDACTED, str(error))[:500]


def _run_id(now: str) -> str:
    return "refresh-" + now.replace("-", "").replace(":", "").replace("Z", "Z")


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _canonical_bytes(payload)
    temp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=f".{path.name}-", delete=False) as handle:
            temp = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


@contextmanager
def _exclusive_lock(root: Path) -> Iterator[None]:
    import fcntl

    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".production-refresh.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RefreshLockedError("another production refresh run is active") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_football(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("games"), list) or not payload["games"]:
        raise RuntimeError("football scorer did not create a non-empty canonical games snapshot")
    stored = payload.get("snapshot_sha256")
    if not isinstance(stored, str) or len(stored) != 64 or any(c not in "0123456789abcdef" for c in stored.lower()):
        raise RuntimeError("football scorer snapshot SHA-256 is missing or malformed")
    # Shared identity contract with the scorer: hash excludes snapshot_sha256
    # itself and is independent of file formatting.
    if football_snapshot_hash(payload) != stored:
        raise RuntimeError("football scorer canonical snapshot SHA-256 mismatch")
    return payload


def _validate_sleeper(config: RefreshConfig) -> SleeperQBSource:
    source = SleeperQBSource.load(config.repository_root, prediction_as_of_utc=config.prediction_as_of_utc)
    if source.freshness_state != "FRESH" or source.source_warning_state is not None:
        raise RuntimeError(
            f"Sleeper source is not ready: freshness={source.freshness_state} warning={source.source_warning_state}"
        )
    return source


def run_refresh(config: RefreshConfig) -> tuple[RefreshOutcome, dict[str, Any]]:
    """Execute exactly one staged refresh; only the explicit live branch acquires.

    A successful provider response is persisted by ``acquire_live_response`` before
    any parse or normalization. Every later stage uses that saved response in the
    same run directory and this function never retries the provider.
    """
    if config.live == (config.market_response is not None):
        raise ValueError("provide exactly one of live acquisition or a saved market response")
    started = _utc_now()
    run_id = _run_id(started)
    run_dir = config.run_root / run_id
    summary: dict[str, Any] = {
        "schema_version": "nfl-edge-production-refresh-v1",
        "run_id": run_id,
        "started_at_utc": started,
        "finished_at_utc": None,
        "outcome": None,
        "provider_request_count": 0,
        "credits_consumed": None,
        "sleeper_snapshot_id": None,
        "prediction_as_of_utc": config.prediction_as_of_utc,
        "football_snapshot_sha256": None,
        "market_snapshot_version": None,
        "market_snapshot_sha256": None,
        "product_version": None,
        "product_sha256": None,
        "publication_result": None,
        "prospective_capture_result": "DISABLED" if config.prospective_dir is None else "PENDING",
        "prospective_publication_id": None,
        "prospective_source_product_sha256": None,
        "prospective_runtime_path": None,
        "prospective_capture_error_type": None,
        "prospective_capture_error_message": None,
        "error_type": None,
        "error_message": None,
    }

    def finish(outcome: RefreshOutcome, error: BaseException | None = None) -> tuple[RefreshOutcome, dict[str, Any]]:
        summary["outcome"] = outcome.value
        summary["finished_at_utc"] = _utc_now()
        if error is not None:
            summary["error_type"] = type(error).__name__
            summary["error_message"] = _redact_error(error)
        if outcome is RefreshOutcome.SUCCESS:
            summary["publication_result"] = "PUBLISHED"
        _atomic_json(run_dir / "run-status.json", summary)
        _atomic_json(config.run_root / "latest-status.json", summary)
        return outcome, summary

    try:
        with _exclusive_lock(config.run_root):
            try:
                run_dir.mkdir(parents=True, exist_ok=False)
            except FileExistsError:
                # Subsecond uniqueness via a disambiguating suffix; the lock already
                # serializes runs, so this only guards same-second re-entry.
                for suffix in range(1, 100):
                    candidate = config.run_root / (run_id + f"-{suffix:02d}")
                    try:
                        candidate.mkdir(parents=True, exist_ok=False)
                    except FileExistsError:
                        continue
                    run_id = candidate.name
                    run_dir = candidate
                    break
                else:
                    raise RuntimeError("could not allocate a unique run directory within the same second")
                summary["run_id"] = run_id
            try:
                sleeper = _validate_sleeper(config)
                summary["sleeper_snapshot_id"] = sleeper.snapshot_id
                _atomic_json(
                    run_dir / "sleeper-source.json",
                    {
                        "snapshot_id": sleeper.snapshot_id,
                        "observed_at_utc": sleeper.observed_at_utc,
                        "freshness": sleeper.freshness_contract(),
                        "source_warning_state": sleeper.source_warning_state,
                    },
                )
            except Exception as exc:
                return finish(RefreshOutcome.SLEEPER_NOT_READY, exc)

            football_path = run_dir / "football" / "NFL_EDGE_2026_WEEK1_FOOTBALL_V1.json"
            try:
                overrides = load_overrides(config.repository_root / DEFAULT_OVERRIDES)
                football = score_week1(
                    repository_root=config.repository_root,
                    prediction_as_of_utc=config.prediction_as_of_utc,
                    resolver=SleeperExpectedQBResolver(sleeper, overrides=overrides),
                )
                football_path.parent.mkdir(parents=True, exist_ok=True)
                football_path.write_bytes(canonical_snapshot_bytes(football))
                football = _validate_football(football_path)
                summary["football_snapshot_sha256"] = _sha256(football_path)
            except Exception as exc:
                return finish(RefreshOutcome.SCORING_FAILED, exc)

            schedule = load_week1_schedule(config.repository_root / "data/live/2026/week1_schedule_v1.json")
            capture_events: list[dict[str, Any]] | None = None
            capture_metadata: dict[str, Any] | None = None
            try:
                if config.live:
                    # This is the single live-acquisition seam in one run. It has no
                    # retry path; record the one bounded attempt even if it fails.
                    summary["provider_request_count"] = 1
                    capture = acquire_live_response(schedule=schedule, output_dir=run_dir / "raw", live=True)
                else:
                    assert config.market_response is not None
                    capture_events, capture_metadata = load_capture(
                        config.market_response,
                        metadata_path=config.market_metadata,
                        acquired_at_utc=config.prediction_as_of_utc,
                    )
                    # The CLI as-of override above may have shadowed the saved
                    # capture timestamp inside load_capture. Restore the original
                    # saved value: replay market identity is frozen at capture
                    # time and must never depend on the invocation as-of.
                    saved_ts = None
                    if config.market_metadata is not None and Path(config.market_metadata).is_file():
                        saved_ts = str(json.loads(Path(config.market_metadata).read_text(encoding="utf-8")).get("acquired_at_utc") or "")
                    if not saved_ts and Path(config.market_response).with_suffix(".meta.json").is_file():
                        saved_ts = str(
                            json.loads(Path(config.market_response).with_suffix(".meta.json").read_text(encoding="utf-8")).get("acquired_at_utc") or ""
                        )
                    if saved_ts:
                        capture_metadata["captured_acquired_at_utc"] = saved_ts
                        capture_metadata["acquired_at_utc"] = saved_ts
                    raw_copy = run_dir / "raw" / config.market_response.name
                    raw_copy.parent.mkdir(parents=True, exist_ok=True)
                    raw_copy.write_bytes(config.market_response.read_bytes())
                    metadata_copy = raw_copy.with_suffix(".meta.json")
                    _atomic_json(metadata_copy, _redact_value(dict(capture_metadata)))
                    # Reuse the loaded replay below; live capture is handled in the common branch.
                    capture = None
            except Exception as exc:
                return finish(RefreshOutcome.MARKET_ACQUISITION_FAILED, exc)

            try:
                if capture is None:
                    if capture_events is None or capture_metadata is None:
                        raise RuntimeError("replay capture was not loaded")
                    # Replay must freeze the original capture timestamp: the saved
                    # metadata acquired_at_utc is the market identity anchor. The
                    # CLI as-of time must never override it.
                    events, metadata = capture_events, capture_metadata
                    original_capture_ts = metadata.get("captured_acquired_at_utc")
                    if original_capture_ts:
                        metadata["acquired_at_utc"] = str(original_capture_ts)
                else:
                    events, metadata = load_capture(capture.response_path, metadata_path=capture.metadata_path)
                market = normalize_market_snapshot(
                    schedule=schedule,
                    events=events,
                    acquired_at_utc=str(metadata["acquired_at_utc"]),
                    response_sha256=str(metadata["response_sha256"]),
                    credits_consumed=metadata.get("credits_consumed"),
                    credits_remaining=metadata.get("credits_remaining"),
                )
                market_path = run_dir / "market" / "NFL_EDGE_LIVE_MARKET_V1.json"
                market_path.parent.mkdir(parents=True, exist_ok=True)
                market_path.write_bytes(market_snapshot_bytes(market))
                summary["credits_consumed"] = metadata.get("credits_consumed")
                summary["market_snapshot_version"] = market.get("market_snapshot_version") or market.get("snapshot_version")
                summary["market_snapshot_sha256"] = market["snapshot_sha256"]
            except Exception as exc:
                return finish(RefreshOutcome.MARKET_NORMALIZATION_FAILED, exc)

            try:
                decision_state = load_entering_2026_product_state(
                    config.repository_root / "data/live/2026/entering_product_state_v1.json"
                )
                product, proof = build_product_snapshot(
                    root=config.repository_root,
                    football_snapshot=football,
                    market_snapshot=market,
                    decision_state=decision_state,
                )
                replay, replay_proof = build_product_snapshot(
                    root=config.repository_root,
                    football_snapshot=football,
                    market_snapshot=market,
                    decision_state=decision_state,
                )
                product_bytes = product_snapshot_bytes(product)
                if product_bytes != product_snapshot_bytes(replay) or proof != replay_proof:
                    raise RuntimeError("deterministic product replay failed")
                validate_product_snapshot(product)
                candidate_path = run_dir / "product" / "NFL_EDGE_PRODUCT_API_V1.json"
                candidate_path.parent.mkdir(parents=True, exist_ok=True)
                candidate_path.write_bytes(product_bytes)
                proof_payload = {
                    **proof,
                    "deterministic_replay": "PASS",
                    "provider_request_count": summary["provider_request_count"],
                }
                _atomic_json(run_dir / "product" / "deterministic-proof.json", proof_payload)
                summary["product_version"] = product["product_version"]
                summary["product_sha256"] = hashlib.sha256(product_bytes).hexdigest()
            except Exception as exc:
                return finish(RefreshOutcome.MATERIALIZATION_FAILED, exc)

            try:
                immutable = ProductStore(config.publication_dir).publish(product)
                if not immutable.is_file():
                    raise RuntimeError("publisher returned missing immutable snapshot")
                current = ProductStore(config.publication_dir).load_latest(required=True)
                if current is None or current["product_version"] != product["product_version"]:
                    raise RuntimeError("published latest product did not match candidate")
                summary["immutable_snapshot"] = str(immutable)
            except Exception as exc:
                return finish(RefreshOutcome.PUBLICATION_FAILED, exc)

            # Prospective evidence is observational and begins only after the product
            # is production-authoritative. Failure here is visible but cannot roll
            # back a successful publication or alter the refresh SUCCESS outcome.
            if config.prospective_dir is not None:
                try:
                    capture = capture_published_product(
                        current,
                        runtime_root=config.prospective_dir,
                        published_at_utc=_utc_now(),
                    )
                    if capture["source_product_sha256"] != summary["product_sha256"]:
                        raise RuntimeError(
                            "prospective source product hash did not match published product hash"
                        )
                    summary.update(
                        prospective_capture_result=str(capture["status"]),
                        prospective_publication_id=str(capture["publication_id"]),
                        prospective_source_product_sha256=str(capture["source_product_sha256"]),
                        prospective_runtime_path=str(capture["runtime_path"]),
                    )
                except Exception as exc:
                    summary["prospective_capture_result"] = "FAILED"
                    summary["prospective_capture_error_type"] = type(exc).__name__
                    summary["prospective_capture_error_message"] = _redact_error(exc)
            return finish(RefreshOutcome.SUCCESS)
    except RefreshLockedError as exc:
        # A locked invocation creates no run directory and therefore cannot interleave artifacts.
        summary.update(
            outcome=RefreshOutcome.LOCKED.value,
            finished_at_utc=_utc_now(),
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return RefreshOutcome.LOCKED, summary


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--publication-dir", type=Path, required=True)
    parser.add_argument("--prospective-dir", type=Path)
    parser.add_argument("--prediction-as-of-utc", default=_utc_now())
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[3])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--live", action="store_true")
    source.add_argument("--market-response", type=Path)
    parser.add_argument("--market-metadata", type=Path)
    args = parser.parse_args(argv)
    outcome, summary = run_refresh(
        RefreshConfig(
            repository_root=args.repository_root,
            run_root=args.run_root,
            publication_dir=args.publication_dir,
            prediction_as_of_utc=args.prediction_as_of_utc,
            live=args.live,
            market_response=args.market_response,
            market_metadata=args.market_metadata,
            prospective_dir=args.prospective_dir,
        )
    )
    print(json.dumps(summary, sort_keys=True))
    return EXIT_CODES[outcome]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
