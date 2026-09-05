#!/usr/bin/env python3
"""Build a single-file, browser-openable NFL EDGE UI review artifact.

This is preview tooling only. It snapshots the local CI smoke API into an embedded
fetch shim, inlines the production frontend assets, and bundles the real frontend
modules into isolated script scopes. The result can be opened directly from disk
without a server so UI review does not require deploying the feature branch.

The standalone review artifact emulates a signed-in Normal-risk user. If the
bounded smoke fixture contains no actionable retail offer, one captured offer is
promoted to a clearly preview-only BET response so reviewers can inspect the full
BET -> Log Wager interaction. Production evaluator output is never modified.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
CORE_EXPORTS = [
    "RISK_PROFILES", "WAGER_STATUSES", "esc", "odds", "line", "money", "pct", "units",
    "healthPresentation", "playThroughPresentation", "roofPresentation", "headlinePresentation",
    "buildHeadlineWagerPayload", "buildExactWagerPayload",
]
COMPARE_EXPORTS = ["compareOffer", "comparisonLabel", "findPinnyOffer", "gameComparisonRows"]
PREVIEW_USER = {
    "schema_version": "NFL_EDGE_USER_STATE_V1",
    "user_id": "ui-preview-user",
    "username": "Preview User",
    "bankroll": "1000.00",
    "risk_profile": "Normal",
    "created_at": "2026-09-05T00:00:00Z",
    "updated_at": "2026-09-05T00:00:00Z",
}


def _json_request(base_url: str, path: str, *, method: str = "GET", body: dict | None = None) -> tuple[int, object]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base_url.rstrip("/") + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload = json.loads(raw) if raw else {"detail": str(exc)}
        except json.JSONDecodeError:
            payload = {"detail": raw or str(exc)}
        return exc.code, payload


def _offer_key(offer: dict) -> str:
    line = "" if offer.get("line") is None else str(offer.get("line"))
    return "|".join(
        str(offer.get(k, "")) for k in ("game_id", "market_type", "selection", "book")
    ) + f"|{line}|{offer.get('price', '')}"


def _preview_bet_response(source: dict | None, product_version: str) -> dict:
    response = copy.deepcopy(source or {})
    response["product_version"] = response.get("product_version") or product_version
    response["recommended_dollars"] = "7.50"
    evaluation = response.setdefault("evaluation", {})
    evaluation.update(
        verdict="BET",
        supported=True,
        recommended_units=0.75,
        probability=evaluation.get("probability") if evaluation.get("probability") is not None else 0.565,
        trust_probability=evaluation.get("trust_probability") if evaluation.get("trust_probability") is not None else 0.548,
        ev=evaluation.get("ev") if evaluation.get("ev") is not None else 0.061,
    )
    return response


def _snapshot_api(base_url: str) -> dict:
    health_status, health = _json_request(base_url, "/api/v1/health")
    product_status, product = _json_request(base_url, "/api/v1/product/latest")
    games_status, games = _json_request(base_url, "/api/v1/games")
    if health_status != 200 or product_status != 200 or games_status != 200:
        raise RuntimeError("preview builder requires a healthy local smoke API")

    details: dict[str, object] = {}
    evaluations: dict[str, object] = {}
    fallback_evaluation = None
    first_offer_key = None
    for game_summary in (games or {}).get("games", []):
        game_id = str(game_summary["game_id"])
        status, detail = _json_request(base_url, f"/api/v1/games/{urllib.parse.quote(game_id, safe='')}")
        if status != 200:
            continue
        details[game_id] = detail
        game = (detail or {}).get("game", {})
        board = game.get("market_board", {}) or {}
        for market in ("moneyline", "spread", "total"):
            for book in ("DRAFTKINGS", "FANDUEL"):
                for raw_offer in ((board.get(market, {}) or {}).get(book, []) or []):
                    offer = {
                        "game_id": game_id,
                        "market_type": market.upper(),
                        "selection": raw_offer.get("selection"),
                        "book": book,
                        "line": raw_offer.get("line"),
                        "price": raw_offer.get("price"),
                    }
                    key = _offer_key(offer)
                    first_offer_key = first_offer_key or key
                    eval_status, evaluation = _json_request(
                        base_url, "/api/v1/evaluate-offer", method="POST", body=offer
                    )
                    if eval_status == 200:
                        evaluations[key] = evaluation
                        fallback_evaluation = fallback_evaluation or evaluation

    product_version = (product or {}).get("product", {}).get("product_version", "preview")
    if fallback_evaluation is None:
        fallback_evaluation = {
            "product_version": product_version,
            "recommended_dollars": None,
            "evaluation": {
                "verdict": "UNSUPPORTED", "recommended_units": 0,
                "probability": None, "trust_probability": None, "ev": None,
                "play_through": None, "value_at": None,
            },
        }

    bet_key = next(
        (key for key, value in evaluations.items() if (value or {}).get("evaluation", {}).get("verdict") == "BET"),
        None,
    )
    forced_bet = False
    if bet_key is None and first_offer_key is not None:
        bet_key = first_offer_key
        evaluations[bet_key] = _preview_bet_response(evaluations.get(bet_key), product_version)
        forced_bet = True
    elif bet_key is not None:
        evaluations[bet_key] = _preview_bet_response(evaluations[bet_key], product_version)

    return {
        "health": health,
        "product": product,
        "games": games,
        "details": details,
        "evaluations": evaluations,
        "fallback_evaluation": fallback_evaluation,
        "preview_user": PREVIEW_USER,
        "preview_bet_key": bet_key,
        "preview_bet_forced": forced_bet,
    }


def _without_exports(source: str) -> str:
    return re.sub(r"\bexport\s+", "", source)


def _without_imports(source: str) -> str:
    return re.sub(r"^import\s+.*?;\s*$", "", source, flags=re.MULTILINE)


def _module_bundle(snapshot: dict) -> str:
    api_src = _without_exports((FRONTEND / "api.js").read_text())
    core_src = _without_exports((FRONTEND / "ui-core.js").read_text())
    compare_src = _without_exports((FRONTEND / "market-compare.js").read_text())
    app_src = _without_imports((FRONTEND / "app.js").read_text())
    ux_src = _without_imports((FRONTEND / "ux.js").read_text())
    payload = json.dumps(snapshot, separators=(",", ":")).replace("</", "<\\/")

    fetch_shim = f"""
const __NFL_EDGE_PREVIEW={payload};
const __nativeFetch=globalThis.fetch?.bind(globalThis);
const __jsonResponse=(payload,status=200)=>Promise.resolve(new Response(JSON.stringify(payload),{{status,headers:{{'content-type':'application/json'}}}}));
const __offerKey=o=>[o.game_id,o.market_type,o.selection,o.book,o.line==null?'':o.line,o.price].map(v=>String(v??'')).join('|');
globalThis.fetch=async(input,init={{}})=>{{
  const raw=typeof input==='string'?input:(input?.url||String(input));
  let url;
  try{{url=new URL(raw,'https://preview.invalid')}}catch{{return __nativeFetch?__nativeFetch(input,init):Promise.reject(new Error('preview fetch failed'))}}
  if(!url.pathname.startsWith('/api/'))return __nativeFetch?__nativeFetch(input,init):Promise.reject(new Error('preview external fetch unavailable'));
  const method=String(init?.method||input?.method||'GET').toUpperCase();
  const path=url.pathname;
  if(method==='GET'&&path==='/api/v1/health')return __jsonResponse(__NFL_EDGE_PREVIEW.health);
  if(method==='GET'&&path==='/api/v1/product/latest')return __jsonResponse(__NFL_EDGE_PREVIEW.product);
  if(method==='GET'&&path==='/api/v1/games')return __jsonResponse(__NFL_EDGE_PREVIEW.games);
  if(method==='GET'&&path.startsWith('/api/v1/games/')){{
    const id=decodeURIComponent(path.slice('/api/v1/games/'.length));
    const detail=__NFL_EDGE_PREVIEW.details[id];
    return detail?__jsonResponse(detail):__jsonResponse({{detail:'Preview game not found.'}},404);
  }}
  if(method==='POST'&&path==='/api/v1/evaluate-offer'){{
    let body={{}};try{{body=JSON.parse(init?.body||'{{}}')}}catch{{}}
    return __jsonResponse(__NFL_EDGE_PREVIEW.evaluations[__offerKey(body)]||__NFL_EDGE_PREVIEW.fallback_evaluation);
  }}
  if(method==='GET'&&path==='/api/v1/auth/me')return __jsonResponse({{user:__NFL_EDGE_PREVIEW.preview_user}});
  if(method==='GET'&&path==='/api/v1/profile')return __jsonResponse(__NFL_EDGE_PREVIEW.preview_user);
  if(method==='GET'&&path==='/api/v1/wagers')return __jsonResponse({{wagers:[]}});
  if(path.startsWith('/api/v1/wagers'))return __jsonResponse({{detail:'Preview mode — wager persistence is disabled.'}},503);
  if(path.startsWith('/api/v1/auth/'))return __jsonResponse({{detail:'Preview mode — authentication changes are disabled.'}},503);
  if(path==='/api/v1/profile')return __jsonResponse({{detail:'Preview mode — profile writes are disabled.'}},503);
  return __jsonResponse({{detail:'This server action is disabled in the UI preview.'}},503);
}};
"""

    api_bundle = f"const __api=(()=>{{\n{api_src}\nreturn {{ApiClient,ApiError}};\n}})();"
    core_returns = ",".join(CORE_EXPORTS)
    core_bundle = f"const __core=(()=>{{\n{core_src}\nreturn {{{core_returns}}};\n}})();"
    compare_returns = ",".join(COMPARE_EXPORTS)
    compare_bundle = f"const __compare=(()=>{{\n{compare_src}\nreturn {{{compare_returns}}};\n}})();"
    app_imports = ",".join(CORE_EXPORTS)
    app_bundle = (
        "(()=>{const {ApiClient,ApiError}=__api;"
        f"const {{{app_imports}}}=__core;"
        "const {compareOffer,comparisonLabel,findPinnyOffer}=__compare;\n"
        f"{app_src}\n}})();"
    )
    ux_bundle = (
        "(()=>{const {ApiClient}=__api;const {gameComparisonRows}=__compare;\n"
        f"{ux_src}\n}})();"
    )
    return "\n".join((fetch_shim, api_bundle, core_bundle, compare_bundle, app_bundle, ux_bundle))


def build(base_url: str, output: Path) -> None:
    snapshot = _snapshot_api(base_url)
    html = (FRONTEND / "index.html").read_text()
    css = "\n".join(
        (FRONTEND / name).read_text() for name in ("styles.css", "saved-ux.css", "ui-polish.css")
    )
    html = re.sub(r'<link rel="manifest"[^>]*>', '', html)
    html = re.sub(r'<link rel="apple-touch-icon"[^>]*>', '', html)
    html = re.sub(r'<link rel="stylesheet" href="\./(?:styles|saved-ux|ui-polish)\.css">', '', html)
    html = html.replace("</head>", f"<style>\n{css}\n</style></head>")
    html = re.sub(r'<script type="module" src="\./(?:app|ux)\.js"></script>', '', html)
    html = html.replace(
        "</body>",
        "<script>\n" + _module_bundle(snapshot) + "\n</script>\n"
        "<!-- Standalone UI review artifact: signed-in preview state; API writes/install are intentionally disabled. -->\n"
        "</body>",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html)
    print(f"UI_PREVIEW_BUILT={output}")
    print(f"UI_PREVIEW_BET_KEY={snapshot.get('preview_bet_key')}")
    print(f"UI_PREVIEW_BET_FORCED={snapshot.get('preview_bet_forced')}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8770")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.base_url, args.output)


if __name__ == "__main__":
    main()
