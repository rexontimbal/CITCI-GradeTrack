"""One-off cleanup: images/citci-banner.png (and static/img/citci-logo.png,
the same file) are a flat RGB PNG with a FAKE transparency checkerboard
baked into the pixels instead of a real alpha channel. This flood-fills the
checkerboard from the image borders and makes those pixels actually
transparent, leaving the seal (including its soft lavender outer glow) intact.

Usage: python scripts/clean_seal.py
"""

from collections import deque
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "images" / "citci-banner.png"
OUT_FULL = ROOT / "static" / "img" / "citci-seal.png"
OUT_SMALL = ROOT / "static" / "img" / "citci-seal-256.png"
OUT_LOGO = ROOT / "static" / "img" / "citci-logo.png"

# Checkerboard squares are neutral gray/white (R==G==B); the seal's lavender
# glow edge is faintly blue-tinted, so a tight "how neutral is this pixel"
# tolerance separates the two without eating into the glow.
NEUTRAL_TOLERANCE = 6
LIGHT_THRESHOLD = 150
FEATHER_RADIUS = 1


def flood_fill_checkerboard_mask(img):
    """BFS flood fill from the four image borders over neutral, light
    (checkerboard) pixels. Returns a bytearray mask, 1 = checkerboard."""
    px = img.load()
    w, h = img.size
    visited = bytearray(w * h)

    def is_checkerboard(x, y):
        r, g, b = px[x, y][:3]
        return (max(r, g, b) - min(r, g, b)) <= NEUTRAL_TOLERANCE and min(r, g, b) >= LIGHT_THRESHOLD

    queue = deque()

    def seed(x, y):
        idx = y * w + x
        if not visited[idx] and is_checkerboard(x, y):
            visited[idx] = 1
            queue.append((x, y))

    for x in range(w):
        seed(x, 0)
        seed(x, h - 1)
    for y in range(h):
        seed(0, y)
        seed(w - 1, y)

    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h:
                idx = ny * w + nx
                if not visited[idx] and is_checkerboard(nx, ny):
                    visited[idx] = 1
                    queue.append((nx, ny))

    return visited


def clean(src_path):
    img = Image.open(src_path).convert("RGB")
    w, h = img.size
    mask = flood_fill_checkerboard_mask(img)

    alpha = Image.new("L", (w, h), 255)
    alpha_px = alpha.load()
    for y in range(h):
        row = y * w
        for x in range(w):
            if mask[row + x]:
                alpha_px[x, y] = 0

    alpha = alpha.filter(ImageFilter.GaussianBlur(FEATHER_RADIUS))

    out = img.convert("RGBA")
    out.putalpha(alpha)
    return out


def main():
    print(f"Cleaning {SRC} ...")
    cleaned = clean(SRC)

    OUT_FULL.parent.mkdir(parents=True, exist_ok=True)
    cleaned.save(OUT_FULL)
    print(f"Saved {OUT_FULL} ({cleaned.size[0]}x{cleaned.size[1]})")

    small = cleaned.resize((256, 256), Image.LANCZOS)
    small.save(OUT_SMALL)
    print(f"Saved {OUT_SMALL} (256x256)")

    # static/img/citci-logo.png is byte-identical to the banner — same bug.
    cleaned.save(OUT_LOGO)
    print(f"Saved {OUT_LOGO} (same fix applied, filename kept)")


if __name__ == "__main__":
    main()
