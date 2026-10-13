from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from inventory.config import Config
from inventory.db import Database
from inventory.store import Store


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(Database(tmp_path / "t.db"))


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    return Config(
        data_dir=tmp_path, public_url="", printd_url="http://printd.invalid", web_dir=None,
        google_vision_api_key="", anthropic_api_key="", claude_model="x",
        embed_enabled=False, model_base_url="", label_font="", host="", port=0,
    )


def jpeg(color=(200, 30, 30), size=(640, 480)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()
