"""Image -> TSPL job encoding.

The KNAON Y813BT (and most cheap 4x6 "shipping label" printers: iDPRT, Munbyn,
HPRT, Beeprt…) speak TSC's TSPL. KNAON's own Linux driver is the CUPS
`rastertolabel` filter in TSPL mode; the strings in its binary show exactly the
job shape reproduced here:

    SIZE 4,6 / GAP 3 mm,0 mm / DIRECTION / REFERENCE 0,0 / DENSITY / SPEED / CLS
    BITMAP 0,0,<bytes/row>,<rows>,0,<raw 1bpp rows>
    PRINT 1,<copies>

BITMAP bit polarity: 1 = blank, 0 = burn a dot — which is exactly how PIL packs
a mode "1" image (white=1), so the rows go out as-is.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageOps

DPI = 203


@dataclass(frozen=True)
class Media:
    width_in: float = 4.0
    height_in: float = 6.0
    gap_mm: float = 3.0
    gap_offset_mm: float = 0.0

    @property
    def width_dots(self) -> int:
        return round(self.width_in * DPI)

    @property
    def height_dots(self) -> int:
        return round(self.height_in * DPI)


@dataclass(frozen=True)
class Settings:
    density: int = 8      # 0..15 burn darkness
    speed: int = 4        # inches/sec
    direction: int = 0    # 0/1 — flip 180° if labels come out upside down
    invert: bool = False  # escape hatch should a firmware use the opposite bit polarity


def fit(img: Image.Image, media: Media) -> Image.Image:
    """Scale/rotate/pad an arbitrary image onto the label, as 1-bit."""
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img.convert("RGBA"))
    img = img.convert("L")
    w, h = media.width_dots, media.height_dots
    # Landscape artwork on portrait media: rotate rather than shrink.
    if (img.width > img.height) != (w > h) and img.width != img.height:
        img = img.rotate(90, expand=True)
    if img.size != (w, h):
        img = ImageOps.contain(img, (w, h), Image.Resampling.LANCZOS)
        canvas = Image.new("L", (w, h), 255)
        canvas.paste(img, ((w - img.width) // 2, (h - img.height) // 2))
        img = canvas
    # Hard threshold, no dithering: labels are text + QR, which must stay crisp.
    return img.point(lambda v: 255 if v >= 128 else 0, mode="1")


def encode(img: Image.Image, media: Media = Media(), settings: Settings = Settings(),
           copies: int = 1) -> bytes:
    bw = fit(img, media)
    if settings.invert:
        bw = ImageOps.invert(bw.convert("L")).convert("1")
    row_bytes = (bw.width + 7) // 8
    header = "\r\n".join([
        f"SIZE {media.width_in:g},{media.height_in:g}",
        f"GAP {media.gap_mm:g} mm,{media.gap_offset_mm:g} mm",
        f"DIRECTION {settings.direction}",
        "REFERENCE 0,0",
        f"DENSITY {settings.density}",
        f"SPEED {settings.speed}",
        "CLS",
        f"BITMAP 0,0,{row_bytes},{bw.height},0,",
    ]).encode("ascii")
    # PIL pads each mode-"1" row to a whole byte, matching row_bytes.
    return header + bw.tobytes() + f"\r\nPRINT 1,{copies}\r\n".encode("ascii")


def calibrate() -> bytes:
    """Ask the printer to measure the label gap (after loading new stock)."""
    return b"GAPDETECT\r\n"


def test_pattern(media: Media = Media()) -> Image.Image:
    from PIL import ImageDraw

    w, h = media.width_dots, media.height_dots
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w - 1, h - 1], outline=0, width=6)
    for i in range(0, w, 40):
        d.line([(i, 0), (i, 30)], fill=0, width=2)
    d.line([(0, 0), (w, h)], fill=0, width=3)
    d.line([(w, 0), (0, h)], fill=0, width=3)
    d.text((40, h // 2 - 40), "printd test", fill=0, font_size=72)
    d.text((40, h // 2 + 50), f'{media.width_in:g}" x {media.height_in:g}" @ {DPI} dpi', fill=0, font_size=40)
    d.text((40, 60), "TOP", fill=0, font_size=60)
    return img
