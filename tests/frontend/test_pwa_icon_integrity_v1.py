from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import sys
import zlib
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
ICONS = FRONTEND / "icons"
PNG_SIG = b"\x89PNG\r\n\x1a\n"

subprocess.run(
    [sys.executable, str(ROOT / "scripts" / "materialize_pwa_icon_assets_v1.py")],
    check=True,
)

EXPECTED_SHA256 = {
    "icon-192-v3.png": "8c6d08ec8f41b6b895126ec864199e59fdb14ccefda85935b6c352c96080b008",
    "icon-512-v3.png": "2a725327d9c09373a4132e869a3440535ff203c5130bfee2b47fbde6c33f0fe9",
    "favicon.ico": "857936a759ca6d738c92c5836908c1b09b4663c64aa87f2dacd1c4afd35ac23b",
}


def _validate_png(path: Path, expected_size: tuple[int, int]) -> None:
    data = path.read_bytes()
    assert data.startswith(PNG_SIG)
    offset = len(PNG_SIG)
    seen_ihdr = False
    seen_idat = False
    seen_iend = False
    size = None
    while offset < len(data):
        assert offset + 12 <= len(data), f"truncated PNG chunk in {path.name}"
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        end = offset + 12 + length
        assert end <= len(data), f"oversized PNG chunk in {path.name}"
        payload = data[offset + 8 : offset + 8 + length]
        stored_crc = struct.unpack(">I", data[offset + 8 + length : end])[0]
        actual_crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
        assert stored_crc == actual_crc, f"bad {chunk_type!r} CRC in {path.name}"
        if chunk_type == b"IHDR":
            assert not seen_ihdr and length == 13
            seen_ihdr = True
            size = struct.unpack(">II", payload[:8])
        elif chunk_type == b"IDAT":
            seen_idat = True
        elif chunk_type == b"IEND":
            assert length == 0
            seen_iend = True
            assert end == len(data), f"bytes after IEND in {path.name}"
            break
        offset = end
    assert seen_ihdr and seen_idat and seen_iend
    assert size == expected_size

    with Image.open(path) as image:
        image.load()
        assert image.format == "PNG"
        assert image.size == expected_size


def test_all_materialized_pwa_png_variants_are_structurally_valid_and_decodable() -> None:
    for name in ("icon-192.png", "icon-192-v2.png", "icon-192-v3.png"):
        _validate_png(ICONS / name, (192, 192))
    for name in ("icon-512.png", "icon-512-v2.png", "icon-512-v3.png"):
        _validate_png(ICONS / name, (512, 512))


def test_compatibility_icon_paths_match_active_approved_artwork() -> None:
    active_192 = (ICONS / "icon-192-v3.png").read_bytes()
    active_512 = (ICONS / "icon-512-v3.png").read_bytes()
    assert (ICONS / "icon-192.png").read_bytes() == active_192
    assert (ICONS / "icon-192-v2.png").read_bytes() == active_192
    assert (ICONS / "icon-512.png").read_bytes() == active_512
    assert (ICONS / "icon-512-v2.png").read_bytes() == active_512


def test_materialized_512_is_exact_nearest_neighbor_derivative_of_approved_192() -> None:
    with Image.open(ICONS / "icon-192-v3.png") as source_image:
        source_image.load()
        expected = source_image.convert("RGB").resize((512, 512), Image.Resampling.NEAREST)
    with Image.open(ICONS / "icon-512-v3.png") as actual_image:
        actual_image.load()
        actual = actual_image.convert("RGB")
    assert actual.tobytes() == expected.tobytes()


def test_approved_icon_hashes_are_locked() -> None:
    paths = {
        "icon-192-v3.png": ICONS / "icon-192-v3.png",
        "icon-512-v3.png": ICONS / "icon-512-v3.png",
        "favicon.ico": FRONTEND / "favicon.ico",
    }
    for name, path in paths.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == EXPECTED_SHA256[name]


def test_root_favicon_is_a_real_decodable_ico_file() -> None:
    data = (FRONTEND / "favicon.ico").read_bytes()
    reserved, image_type, count = struct.unpack("<HHH", data[:6])
    assert reserved == 0
    assert image_type == 1
    assert count == 4
    assert len(data) > 6 + 16 * count
    with Image.open(FRONTEND / "favicon.ico") as image:
        image.load()
        assert image.format == "ICO"
        assert image.size == (64, 64)


def test_manifest_and_head_use_fresh_v3_icon_urls() -> None:
    manifest = json.loads((FRONTEND / "manifest.webmanifest").read_text())
    assert [icon["src"] for icon in manifest["icons"]] == [
        "./icons/icon-192-v3.png",
        "./icons/icon-512-v3.png",
    ]
    html = (FRONTEND / "index.html").read_text()
    assert 'rel="shortcut icon" href="./favicon.ico"' in html
    assert 'href="./icons/icon-192-v3.png"' in html
    assert 'href="./icons/icon-512-v3.png"' in html
    assert 'rel="apple-touch-icon" href="./icons/icon-192-v3.png"' in html


def test_service_worker_forces_fresh_v18_icon_cache_population() -> None:
    sw = (FRONTEND / "sw.js").read_text()
    assert "nfl-edge-shell-v18" in sw
    assert "./favicon.ico" in sw
    assert "./icons/icon-192-v3.png" in sw
    assert "./icons/icon-512-v3.png" in sw
    assert "installFreshShell" in sw
    assert "caches.delete(CACHE_NAME)" in sw
    assert "fetch(path,{cache:'reload'})" in sw
    assert "fetch(request,{cache:'no-store'})" in sw


def test_materializer_contract_is_locked_to_approved_source_and_generated_hash() -> None:
    script = (ROOT / "scripts" / "materialize_pwa_icon_assets_v1.py").read_text()
    assert EXPECTED_SHA256["icon-192-v3.png"] in script
    assert EXPECTED_SHA256["icon-512-v3.png"] in script
    assert 'Image.Resampling.NEAREST' in script
    assert 'icon-192-v3.png' in script
    assert 'icon-512-v3.png' in script
