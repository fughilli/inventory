"""Photo storage: normalise uploads (EXIF rotation, size cap, JPEG) + thumbnails."""

from __future__ import annotations

import io
import uuid
from pathlib import Path

from PIL import Image, ImageOps

MAX_EDGE = 1600
THUMB_EDGE = 400


class PhotoStore:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes) -> tuple[str, int, int]:
        """Store an uploaded image; returns (relative file name, width, height)."""
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
        name = uuid.uuid4().hex
        sub = self.root / name[:2]
        sub.mkdir(exist_ok=True)
        rel = f"{name[:2]}/{name}.jpg"
        img.save(self.root / rel, "JPEG", quality=85, optimize=True)
        thumb = img.copy()
        thumb.thumbnail((THUMB_EDGE, THUMB_EDGE), Image.Resampling.LANCZOS)
        thumb.save(self.thumb_path(rel), "JPEG", quality=80, optimize=True)
        return rel, img.width, img.height

    def path(self, rel: str) -> Path:
        return self.root / rel

    def thumb_path(self, rel: str) -> Path:
        return self.root / rel.replace(".jpg", ".thumb.jpg")

    def open(self, rel: str) -> Image.Image:
        return Image.open(self.path(rel)).convert("RGB")

    def delete(self, rel: str) -> None:
        for p in (self.path(rel), self.thumb_path(rel)):
            p.unlink(missing_ok=True)
