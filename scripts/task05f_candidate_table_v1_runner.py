#!/usr/bin/env python3
"""Task05F common candidate-table materializer.

This is a downstream interface replay of the already-frozen evaluator + Phase F
+ Play Through V1.1 stack. It does not re-evaluate or tune those policies.
Historical outcomes are emitted only to a separate diagnostic sidecar and never
appear in the production-facing candidate table.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from typing import Any

import polars as pl
import yaml

from nfl_edge.value.candidate_table import (
    BookOfferContext,
    CandidateOfferContext,
    OUTCOME_FIELDS,
    PRESERVED_FIELDS,
    assert_preserved_fields,
    build_candidate_table,
    build_historical_outcome_sidecar,
    make_candidate_id,
)


ROOT = Path(__file__).resolve().parents[1]
DEV = [2020, 2021, 2022, 2023, 2024]
SEALED = {2025}
VERSION = "task05f_common_candidate_table_v1"
CONFIG = ROOT / "config" / "task05f_candidate_table_v1.yaml"
PHASE_G_CONFIG = ROOT / "config" / "task05f_play_through_v1_1_prereg.yaml"
PHASE_G_RUNNER = ROOT / "scripts" / "task05f_play_through_v1_runner.py"
V1_RUNNER = ROOT / "scripts" / "task05f_evaluator_rebuild_runner.py"


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_yaml(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    return yaml.safe_load(raw), hashlib.sha256(raw).hexdigest()


def _json_write(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _offer(offer) -> BookOfferContext | None:
    if offer is None:
        return None
    return BookOfferContext(
        None if offer.line is None else float(offer.line),
        int(offer.price_american),
    )


def _same_line(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= 1e-9


def _payload_hash(rows: list[dict[str, Any]], *, candidate_form: bool) -> str:
    payload = []
    for row in rows:
        if candidate_form:
            cid = str(row["candidate_id"])
            values = {field: row.get(field) for field in PRESERVED_FIELDS}
        else:
            cid = make_candidate_id(
                str(row["game_id"]),
                str(row["market_type"]),
                str(row["selected_side"]),
            )
            values = {field: row.get(field) for field in PRESERVED_FIELDS}
        payload.append({"candidate_id": cid, **values})
    payload.sort(key=lambda item: item["candidate_id"])
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _counts(rows: list[dict[str, Any]], field: str, values: tuple[str, ...]) -> dict[str, int]:
    return {value: sum(str(row.get(field)) == value for row in rows) for value in values}


def run(root: Path, config_path: Path, out: Path) -> None:
    root = root.resolve()
    if not config_path.is_absolute():
        config_path = (root / config_path).resolve()
    else:
        config_path = config_path.resolve()
    cfg, config_sha = _read_yaml(config_path)
    expected_rows = int(cfg["candidate_universe"]["expected_rows_for_frozen_2020_2024_fixture"])

    phase_g = _load_script("task05f_candidate_phase_g_runtime", PHASE_G_RUNNER)
    v1 = _load_script("task05f_candidate_v1_market_runtime", V1_RUNNER)

    with tempfile.TemporaryDirectory(prefix="task05f_candidate_upstream_") as tmp:
        phase_g_out = Path(tmp) / "phase_g"
        # Frozen upstream replay only. V1.1 is already accepted and cannot be
        # changed from any downstream candidate/selector diagnostics.
        phase_g.run(root, PHASE_G_CONFIG, phase_g_out)
        upstream_df = pl.read_parquet(phase_g_out / "full_board.parquet")
        seasons = sorted(int(x) for x in upstream_df["season"].unique().to_list())
        if set(seasons).intersection(SEALED):
            raise RuntimeError("sealed 2025 row entered candidate-table upstream")
        if seasons != DEV:
            raise RuntimeError(f"unexpected development seasons {seasons}")
        upstream_rows = upstream_df.to_dicts()
        if len(upstream_rows) != expected_rows:
            raise RuntimeError(f"expected {expected_rows} upstream rows, found {len(upstream_rows)}")

        game_ids = sorted({str(row["game_id"]) for row in upstream_rows})
        market_idx = v1.build_market(root, {gid: {} for gid in game_ids})

        contexts: dict[str, CandidateOfferContext] = {}
        for row in upstream_rows:
            gid = str(row["game_id"])
            market = str(row["market_type"])
            side = str(row["selected_side"])
            cid = make_candidate_id(gid, market, side)
            contexts[cid] = CandidateOfferContext(
                draftkings=_offer(v1._best(market_idx, gid, market, side, books=("draftkings",))),
                fanduel=_offer(v1._best(market_idx, gid, market, side, books=("fanduel",))),
                pinnacle=_offer(v1._pin(market_idx, gid, market, side)),
            )

        candidate_rows = build_candidate_table(upstream_rows, contexts)
        assert_preserved_fields(upstream_rows, candidate_rows)
        if len(candidate_rows) != expected_rows:
            raise RuntimeError("candidate-table row count changed")
        if len({row["candidate_id"] for row in candidate_rows}) != expected_rows:
            raise RuntimeError("candidate_id is not unique")
        if any(OUTCOME_FIELDS.intersection(row) for row in candidate_rows):
            raise RuntimeError("historical outcome leaked into production candidate table")

        # Verify the display context for the selected actionable book reproduces
        # the already-frozen upstream actionable offer exactly.
        by_cid = {row["candidate_id"]: row for row in candidate_rows}
        for upstream in upstream_rows:
            cid = make_candidate_id(
                str(upstream["game_id"]),
                str(upstream["market_type"]),
                str(upstream["selected_side"]),
            )
            candidate = by_cid[cid]
            book = str(upstream["sportsbook"])
            if book not in {"draftkings", "fanduel"}:
                raise RuntimeError(f"unexpected actionable book {book}")
            if candidate[f"{book}_price_american"] != int(upstream["american_odds"]):
                raise RuntimeError(f"{cid}: book context price does not reproduce actionable offer")
            if not _same_line(candidate[f"{book}_line"], upstream.get("line")):
                raise RuntimeError(f"{cid}: book context line does not reproduce actionable offer")

        outcomes = build_historical_outcome_sidecar(upstream_rows)
        if len(outcomes) != expected_rows:
            raise RuntimeError("historical outcome sidecar row count changed")

        upstream_hash = _payload_hash(upstream_rows, candidate_form=False)
        candidate_hash = _payload_hash(candidate_rows, candidate_form=True)
        if upstream_hash != candidate_hash:
            raise RuntimeError("candidate table modified preserved upstream fields")

        out.mkdir(parents=True, exist_ok=True)
        pl.DataFrame(candidate_rows, infer_schema_length=None).write_parquet(
            out / "candidate_table.parquet", compression="zstd"
        )
        pl.DataFrame(outcomes, infer_schema_length=None).write_parquet(
            out / "historical_outcomes.parquet", compression="zstd"
        )

        market_counts = {
            market: sum(row["market_type"] == market for row in candidate_rows)
            for market in ("moneyline", "spread", "total")
        }
        context_coverage = {
            book: sum(row[f"{book}_price_american"] is not None for row in candidate_rows)
            for book in ("draftkings", "fanduel", "pinnacle")
        }
        manifest = {
            "version": VERSION,
            "rows": len(candidate_rows),
            "unique_candidate_ids": len({row["candidate_id"] for row in candidate_rows}),
            "unique_offer_ids": len({row["offer_id"] for row in candidate_rows}),
            "seasons": seasons,
            "sealed_seasons": [2025],
            "market_counts": market_counts,
            "support_counts": _counts(candidate_rows, "supported", ("True", "False")),
            "reliability_counts": _counts(
                candidate_rows, "reliability", ("HIGH", "MEDIUM", "LOW", "UNSUPPORTED")
            ),
            "price_status_counts": _counts(
                candidate_rows, "price_status", ("VALUE", "PLAYABLE", "LEAN", "PASS")
            ),
            "book_context_coverage": context_coverage,
            "outcome_fields_in_candidate_table": [],
            "historical_outcomes_sidecar_rows": len(outcomes),
            "selector_scoring": "NOT_RUN",
        }
        _json_write(out / "candidate_table_manifest.json", manifest)
        _json_write(
            out / "reproduction.json",
            {
                "upstream_rows": len(upstream_rows),
                "candidate_rows": len(candidate_rows),
                "preserved_payload_sha256_upstream": upstream_hash,
                "preserved_payload_sha256_candidate": candidate_hash,
                "preserved_fields_equal": upstream_hash == candidate_hash,
                "actionable_offer_reproduced_from_book_context": True,
                "outcome_firewall": True,
            },
        )
        _json_write(
            out / "provenance.json",
            {
                "version": VERSION,
                "github_sha": os.environ.get("GITHUB_SHA"),
                "scope": "downstream_common_candidate_table_interface",
                "candidate_config": str(config_path.relative_to(root)),
                "candidate_config_sha256": config_sha,
                "phase_g_config": str(PHASE_G_CONFIG.relative_to(root)),
                "phase_g_config_sha256": hashlib.sha256(PHASE_G_CONFIG.read_bytes()).hexdigest(),
                "upstream_replay": "FROZEN_V1_1_MATERIALIZATION_NOT_POLICY_REEVALUATION",
                "development_seasons": DEV,
                "sealed_seasons": [2025],
                "selector_scoring": False,
                "historical_outcomes_excluded_from_candidate_table": True,
            },
        )

    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(CONFIG))
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "task05f" / "candidate_table_v1"))
    args = parser.parse_args()
    run(ROOT, Path(args.config), Path(args.out))
