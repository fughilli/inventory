"""Client for printd, the label-printer agent on the garage Pi."""

from __future__ import annotations

import io

import httpx
from PIL import Image


class PrinterClient:
    def __init__(self, base_url: str, client: httpx.Client | None = None):
        self.base_url = base_url
        self.client = client or httpx.Client(timeout=30)

    def status(self) -> dict:
        try:
            r = self.client.get(f"{self.base_url}/status", timeout=3)
            r.raise_for_status()
            return {"reachable": True, **r.json()}
        except Exception as e:  # noqa: BLE001
            return {"reachable": False, "error": str(e)}

    def print_image(self, img: Image.Image, copies: int = 1) -> dict:
        buf = io.BytesIO()
        img.save(buf, "PNG")
        r = self.client.post(f"{self.base_url}/print", params={"copies": copies},
                             content=buf.getvalue(), headers={"Content-Type": "image/png"})
        r.raise_for_status()
        return r.json()
