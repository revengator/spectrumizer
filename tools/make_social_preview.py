"""Generate the GitHub social-preview card (Open Graph image) for the repo.

Renders a 1280x640 PNG with a ZX Spectrum look: black screen, the iconic
four-colour Spectrum stripe, an AY square wave, and the project name. GitHub has
no API for the social preview, so upload the result by hand:
Settings -> General -> Social preview -> Edit -> Upload an image.

    pip install pillow
    python tools/make_social_preview.py        # -> docs/social-preview.png
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "docs", "social-preview.png")

W, H = 1280, 640
BG = (0, 0, 0)                     # Spectrum black paper
WHITE = (255, 255, 255)
CYAN = (0, 224, 224)              # subtitle
GREY = (150, 156, 166)           # footer
WAVE = (0, 224, 0)               # bright Spectrum green

# The four BRIGHT Spectrum colours of the case stripe (top -> bottom).
STRIPE = [(255, 0, 0), (255, 255, 0), (0, 255, 0), (0, 255, 255)]

# macOS monospace candidates (regular, bold-ish via the .ttc index handled below).
FONT_CANDIDATES = [
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Monaco.ttf",
    "/System/Library/Fonts/SFNSMono.ttf",
    "/System/Library/Fonts/Supplemental/Andale Mono.ttf",
]


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if not os.path.exists(path):
            continue
        try:
            # Menlo.ttc: index 0 = Regular, 1 = Bold.
            idx = 1 if (bold and path.endswith(".ttc")) else 0
            return ImageFont.truetype(path, size, index=idx)
        except Exception:
            continue
    return ImageFont.load_default()


def _square_wave(draw, x0, x1, yc, amp, period, color, width=5):
    """A few cycles of an AY square wave as a polyline."""
    pts, x, hi = [], x0, True
    pts.append((x, yc - amp))
    while x < x1:
        nx = min(x + period // 2, x1)
        y = yc - amp if hi else yc + amp
        pts.append((x, y))
        pts.append((nx, y))
        x, hi = nx, not hi
    draw.line(pts, fill=color, width=width, joint="curve")


def main() -> None:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # Right-edge Spectrum colour stripe (evokes the keyboard-corner flash).
    band_w = 56
    seg = H // len(STRIPE)
    for i, col in enumerate(STRIPE):
        d.rectangle([W - band_w, i * seg, W, (i + 1) * seg], fill=col)

    left = 92
    # Title.
    d.text((left, 138), "spectrumizer", font=_font(110, bold=True), fill=WHITE)
    # Subtitle.
    d.text((left + 4, 288),
           "MIDI → ZX Spectrum AY  ·  PT3 chiptune",
           font=_font(42), fill=CYAN)

    # AY square wave.
    _square_wave(d, left, W - band_w - 110, yc=430, amp=34, period=132, color=WAVE)

    # Footer: install line + URL.
    d.text((left, 556), "$ pip install spectrumizer", font=_font(30), fill=WHITE)
    url = "revengator.github.io/spectrumizer"
    uf = _font(30)
    uw = d.textlength(url, font=uf)
    d.text((W - band_w - 40 - uw, 556), url, font=uf, fill=GREY)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    img.save(OUT, "PNG", optimize=True)
    print(f"wrote {OUT}  ({W}x{H}, {os.path.getsize(OUT) // 1024} KB)")


if __name__ == "__main__":
    main()
