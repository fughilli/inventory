"""Generate the PWA icons (a black tote with a hazard-yellow lid) into public/icons.

    python3 scripts/gen_icons.py      # needs Pillow
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "public" / "icons"
CONCRETE, TOTE, HAZARD = (228, 229, 225), (29, 31, 28), (242, 194, 0)


def tote(size: int, pad: float) -> Image.Image:
    s = size * 4  # supersample, then downscale for smooth edges
    img = Image.new("RGB", (s, s), CONCRETE)
    d = ImageDraw.Draw(img)
    p = s * pad
    w = s - 2 * p
    lid_h = w * 0.16
    top = p + w * 0.14
    d.rounded_rectangle([p, top, s - p, top + lid_h], radius=lid_h * 0.35, fill=HAZARD)
    body_top = top + lid_h + w * 0.035
    inset = w * 0.06
    d.rounded_rectangle([p + inset, body_top, s - p - inset, s - p - w * 0.06], radius=w * 0.07, fill=TOTE)
    # a label on the tote
    lw, lh = w * 0.42, w * 0.22
    cx, cy = s / 2, (body_top + s - p) / 2
    d.rectangle([cx - lw / 2, cy - lh / 2, cx + lw / 2, cy + lh / 2], fill=(255, 255, 255))
    for i in range(3):
        bx = cx - lw / 2 + lw * (0.14 + i * 0.26)
        d.rectangle([bx, cy - lh * 0.22, bx + lw * 0.17, cy + lh * 0.22], fill=TOTE)
    return img.resize((size, size), Image.Resampling.LANCZOS)


OUT.mkdir(parents=True, exist_ok=True)
for size in (180, 192, 512):
    tote(size, 0.1).save(OUT / f"icon-{size}.png")
tote(512, 0.2).save(OUT / "icon-maskable-512.png")  # safe zone for maskable
print("wrote", sorted(p.name for p in OUT.iterdir()))
