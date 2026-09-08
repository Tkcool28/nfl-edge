from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "frontend" / "icons"
SOURCE_192 = ICONS / "icon-192-v3.png"
EXPECTED_192_SHA256 = "8c6d08ec8f41b6b895126ec864199e59fdb14ccefda85935b6c352c96080b008"
EXPECTED_512_SHA256 = "2a725327d9c09373a4132e869a3440535ff203c5130bfee2b47fbde6c33f0fe9"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_png(data: bytes, expected_size: tuple[int, int]) -> Image.Image:
    with Image.open(BytesIO(data)) as image:
        image.load()
        if image.format != "PNG" or image.size != expected_size:
            raise SystemExit(
                f"invalid canonical icon: format={image.format!r} size={image.size!r} expected={expected_size!r}"
            )
        return image.convert("RGB")


def main() -> None:
    source_bytes = SOURCE_192.read_bytes()
    source_sha = _sha256(source_bytes)
    if source_sha != EXPECTED_192_SHA256:
        raise SystemExit(
            f"canonical 192 icon hash mismatch: {source_sha} != {EXPECTED_192_SHA256}"
        )

    source_rgb = _load_png(source_bytes, (192, 192))

    # Compatibility 192 paths are byte-for-byte copies of the approved canonical art.
    for name in ("icon-192.png", "icon-192-v2.png"):
        (ICONS / name).write_bytes(source_bytes)

    # The 512 launcher image is a mechanical nearest-neighbor scale only.
    # No redraw, recolor, quantization, or lossy conversion is performed.
    scaled = source_rgb.resize((512, 512), Image.Resampling.NEAREST)
    buffer = BytesIO()
    scaled.save(buffer, format="PNG")
    generated_512 = buffer.getvalue()
    generated_sha = _sha256(generated_512)
    if generated_sha != EXPECTED_512_SHA256:
        raise SystemExit(
            f"generated 512 icon hash mismatch: {generated_sha} != {EXPECTED_512_SHA256}"
        )

    _load_png(generated_512, (512, 512))
    for name in ("icon-512.png", "icon-512-v2.png", "icon-512-v3.png"):
        (ICONS / name).write_bytes(generated_512)

    print(f"PWA_ICON_192_SHA256={source_sha}")
    print(f"PWA_ICON_512_SHA256={generated_sha}")
    print("PWA_ICON_MATERIALIZATION=PASS")


if __name__ == "__main__":
    main()
