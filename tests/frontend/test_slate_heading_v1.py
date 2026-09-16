from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"


def slate_titles(*weeks: object) -> list[str]:
    expression = (
        "import('./frontend/ui-core.js').then(({slateTitle})=>"
        "console.log(JSON.stringify(process.argv.slice(1).map(JSON.parse).map(slateTitle))))"
    )
    result = subprocess.run(
        ["node", "-e", expression, *map(json.dumps, weeks)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_slate_heading_uses_authoritative_product_week_without_static_week_one_copy():
    index = (FRONTEND / "index.html").read_text()
    app = (FRONTEND / "app.js").read_text()

    assert 'id="slate-title"' in index
    assert "Week 1 slate" not in index
    assert "slateTitle(p?.week)" in app
    assert slate_titles(2, None, 2.5, "2") == ["Week 2 slate", "Slate", "Slate", "Slate"]


def test_existing_product_version_and_game_rendering_contracts_remain_in_render_path():
    app = (FRONTEND / "app.js").read_text()

    assert "$('product-version').textContent=`Product ${p.product_version}`" in app
    assert "state.games.map(g=>`<button class=\"gcard\"" in app
    assert "await api.productLatest()" in app
