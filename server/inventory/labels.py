"""Render 4"x6" bin labels (203 dpi, 1-bit friendly) as PIL images.

Layout (portrait, 812x1218 px):
    ┌──────────────┐
    │    B042      │  huge human-readable code
    │ ┌──────────┐ │
    │ │   QR     │ │  QR -> <public_url>/b/B042 (opens the bin in the PWA,
    │ │          │ │       even from the phone's stock camera app)
    │ └──────────┘ │
    │  Camping     │  bin name (optional)
    │  garage/b/.. │  small URL footer
    └──────────────┘
The print agent (printd) only sees pixels, so the server's preview is exactly
what prints.
"""

from __future__ import annotations

import os
from functools import lru_cache

import qrcode
from PIL import Image, ImageDraw, ImageFont

DPI = 203
WIDTH = 812   # 4in
HEIGHT = 1218  # 6in
MARGIN = 40

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


@lru_cache(maxsize=32)
def font(size: int, path: str = "") -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for p in [path, os.environ.get("INVENTORY_LABEL_FONT", ""), *_FONT_CANDIDATES]:
        if p and os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)  # Pillow >= 10.1 ships a scalable default


def _fit(draw: ImageDraw.ImageDraw, text: str, max_w: int, max_size: int, font_path: str):
    size = max_size
    while size > 12:
        f = font(size, font_path)
        l, t, r, b = draw.textbbox((0, 0), text, font=f)
        if r - l <= max_w:
            return f, (l, t, r, b)
        size = int(size * 0.92)
    f = font(12, font_path)
    return f, draw.textbbox((0, 0), text, font=f)


def _center_text(draw, text, y, max_w, max_size, font_path) -> int:
    """Draw text centred at top=y; returns the bottom y."""
    f, (l, t, r, b) = _fit(draw, text, max_w, max_size, font_path)
    x = (WIDTH - (r - l)) // 2 - l
    draw.text((x, y - t), text, font=f, fill=0)
    return y + (b - t)


def bin_url(base_url: str, code: str) -> str:
    return f"{base_url.rstrip('/')}/b/{code}"


def render_bin_label(code: str, name: str = "", base_url: str = "", font_path: str = "") -> Image.Image:
    img = Image.new("L", (WIDTH, HEIGHT), 255)
    d = ImageDraw.Draw(img)
    inner = WIDTH - 2 * MARGIN

    y = _center_text(d, code, MARGIN, inner, 300, font_path) + 10

    url = bin_url(base_url, code) if base_url else code
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
    qr.add_data(url)
    qr.make(fit=True)
    modules = qr.modules_count
    footer_h = 60 + (110 if name else 0)
    avail = min(inner, HEIGHT - y - MARGIN - footer_h)
    # Integer module size => crisp at 203 dpi; reserve a 2-module quiet zone
    # on each side (enough for phone scanners, and the label is otherwise blank).
    box = max(1, avail // (modules + 4))
    y += 2 * box
    qimg = qr.make_image(fill_color="black", back_color="white").get_image().convert("L")
    qimg = qimg.resize((modules * box, modules * box), Image.Resampling.NEAREST)
    img.paste(qimg, ((WIDTH - qimg.width) // 2, y))
    y += qimg.height + 2 * box

    if name:
        y = _center_text(d, name, y, inner, 90, font_path) + 20
    if base_url:
        _center_text(d, url.split("://", 1)[-1], HEIGHT - MARGIN - 34, inner, 34, font_path)
    # Cut/registration frame helps when peeling labels by hand.
    d.rectangle([8, 8, WIDTH - 9, HEIGHT - 9], outline=0, width=4)
    return img
