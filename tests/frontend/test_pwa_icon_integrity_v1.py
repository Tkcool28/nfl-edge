from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
PNG_SIG = b"\x89PNG\r\n\x1a\n"


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


def test_manifest_pngs_are_structurally_valid() -> None:
    _validate_png(FRONTEND / "icons" / "icon-192-v2.png", (192, 192))
    _validate_png(FRONTEND / "icons" / "icon-512-v2.png", (512, 512))


def test_root_favicon_is_a_real_ico_file() -> None:
    data = (FRONTEND / "favicon.ico").read_bytes()
    reserved, image_type, count = struct.unpack("<HHH", data[:6])
    assert reserved == 0
    assert image_type == 1
    assert count >= 1
    assert len(data) > 6 + 16 * count


def test_service_worker_forces_fresh_icon_cache_population() -> None:
    sw = (FRONTEND / "sw.js").read_text()
    assert "./favicon.ico" in sw
    assert "installFreshShell" in sw
    assert "caches.delete(CACHE_NAME)" in sw
    assert "fetch(path,{cache:'reload'})" in sw
    assert "fetch(request,{cache:'no-store'})" in sw
