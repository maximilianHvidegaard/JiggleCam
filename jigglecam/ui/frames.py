"""Loading capture frames for on-screen playback. No Qt here, so it is easy to test.

Full frames are 2304x1296 JPEGs. Decoding one at full size takes ~60 ms on a
Pi 5, but the screen only needs ~800x450. PIL's draft mode lets the JPEG
decoder scale down by 1/2, 1/4 or 1/8 while decoding, which is several times
faster and uses far less memory. This runs on a worker thread anyway.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def wiggle_order(views: int) -> list[int]:
    """Frame indices for the looping wiggle: 4 views -> [0, 1, 2, 3, 2, 1]."""
    if views < 2:
        return list(range(views))
    return list(range(views)) + list(range(views - 2, 0, -1))


@dataclass(frozen=True)
class DecodedFrame:
    width: int
    height: int
    rgb: bytes  # tightly packed RGB888, width * 3 bytes per line


def decode_for_screen(path: Path, max_w: int, max_h: int) -> DecodedFrame:
    from PIL import Image

    with Image.open(path) as img:
        img.draft("RGB", (max_w, max_h))  # fast JPEG downscale, never below the requested size
        img = img.convert("RGB")
        img.thumbnail((max_w, max_h))
        return DecodedFrame(img.width, img.height, img.tobytes())
