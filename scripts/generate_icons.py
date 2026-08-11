"""Generate the extension's crisp PNG icons from the icon design.

The renderer intentionally uses only the Python standard library so icon
generation works on a clean developer machine.  Drawing at 4x and averaging
down produces smooth edges at 16, 48 and 128 pixels.
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "browser-extension" / "icons"
SCALE = 4


def _png(path: Path, pixels: list[list[tuple[int, int, int, int]]]) -> None:
    h, w = len(pixels), len(pixels[0])
    raw = b"".join(b"\0" + b"".join(bytes(px) for px in row) for row in pixels)

    def chunk(kind: bytes, value: bytes) -> bytes:
        return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value) & 0xffffffff)

    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    path.write_bytes(data)


def _render(size: int) -> list[list[tuple[int, int, int, int]]]:
    # Always draw in a 512px coordinate space (the design is 128 units), then
    # downsample to the requested icon size. This keeps the 16px icon intact.
    n = 128 * SCALE
    px = [[(0, 0, 0, 0) for _ in range(n)] for _ in range(n)]

    def setpx(x: int, y: int, color: tuple[int, int, int, int]) -> None:
        if 0 <= x < n and 0 <= y < n:
            px[y][x] = color

    def rr(x0: float, y0: float, x1: float, y1: float, r: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y0), int(y1) + 1):
            for x in range(int(x0), int(x1) + 1):
                dx = max(x0 + r - x, 0, x - (x1 - r))
                dy = max(y0 + r - y, 0, y - (y1 - r))
                if dx * dx + dy * dy <= r * r:
                    setpx(x, y, color)

    def rect(x0, y0, x1, y1, color):
        for y in range(int(y0), int(y1) + 1):
            for x in range(int(x0), int(x1) + 1): setpx(x, y, color)

    def line(x0, y0, x1, y1, width, color):
        radius = width / 2
        steps = int(math.hypot(x1 - x0, y1 - y0) * 2) + 1
        for i in range(steps + 1):
            t = i / steps; cx = x0 + (x1 - x0) * t; cy = y0 + (y1 - y0) * t
            rr(cx - radius, cy - radius, cx + radius, cy + radius, radius, color)

    def circle(cx, cy, r, color):
        rr(cx - r, cy - r, cx + r, cy + r, r, color)

    # Base gradient with transparent rounded corners.
    for y in range(n):
        t = y / max(n - 1, 1)
        color = (int(23 + 29 * t), int(61 + 59 * t), int(120 + 126 * t), 255)
        for x in range(n):
            r = 27 * SCALE
            dx = max(r - x, 0, x - (n - 1 - r))
            dy = max(r - y, 0, y - (n - 1 - r))
            if dx * dx + dy * dy <= r * r: setpx(x, y, color)
    # Browser window: bright outer silhouette plus dark content panel.
    rr(17*SCALE, 23*SCALE, 111*SCALE, 100*SCALE, 14*SCALE, (255, 255, 255, 238))
    rr(22*SCALE, 28*SCALE, 106*SCALE, 95*SCALE, 9*SCALE, (13, 39, 80, 245))
    # Window outline and top bar.
    line(19*SCALE, 45*SCALE, 109*SCALE, 45*SCALE, 5*SCALE, (255, 255, 255, 245))
    for x, c in ((34, (156, 231, 255, 255)), (48, (255, 255, 255, 255)), (62, (156, 231, 255, 255))): circle(x*SCALE, 35*SCALE, 4*SCALE, c)
    # Assistant face.
    rr(37*SCALE, 53*SCALE, 91*SCALE, 90*SCALE, 16*SCALE, (255, 255, 255, 255))
    circle(54*SCALE, 70*SCALE, 5*SCALE, (23, 61, 120, 255)); circle(74*SCALE, 70*SCALE, 5*SCALE, (23, 61, 120, 255))
    line(53*SCALE, 80*SCALE, 64*SCALE, 84*SCALE, 4*SCALE, (52, 120, 246, 255)); line(64*SCALE, 84*SCALE, 75*SCALE, 80*SCALE, 4*SCALE, (52, 120, 246, 255))
    line(96*SCALE, 16*SCALE, 96*SCALE, 30*SCALE, 5*SCALE, (156, 231, 255, 255)); line(89*SCALE, 23*SCALE, 103*SCALE, 23*SCALE, 5*SCALE, (156, 231, 255, 255))
    # Downsample with a simple box filter.
    out = []
    factor = n / size
    for y in range(size):
        row = []
        for x in range(size):
            y0, y1 = int(y * factor), max(int((y + 1) * factor), int(y * factor) + 1)
            x0, x1 = int(x * factor), max(int((x + 1) * factor), int(x * factor) + 1)
            samples = [px[sy][sx] for sy in range(y0, y1) for sx in range(x0, x1)]
            row.append(tuple(sum(c[i] for c in samples) // len(samples) for i in range(4)))
        out.append(row)
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (16, 48, 128): _png(OUT / f"icon{size}.png", _render(size))
    print(f"icons written to {OUT}")


if __name__ == "__main__": main()
