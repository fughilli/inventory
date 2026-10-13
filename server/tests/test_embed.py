"""Real CLIP check — runs only when model files are available locally.

    INVENTORY_TEST_MODEL_DIR=/path/with/vision.onnx,text.onnx,tokenizer.json pytest
"""

import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

MODEL_DIR = os.environ.get("INVENTORY_TEST_MODEL_DIR")
pytestmark = pytest.mark.skipif(not MODEL_DIR, reason="INVENTORY_TEST_MODEL_DIR not set")


def test_text_and_image_share_a_space():
    from inventory.embed import Embedder

    e = Embedder(Path(MODEL_DIR), base_url="http://unused")
    e._load()
    assert e.ready, e.error
    red = Image.new("RGB", (300, 300), (220, 20, 20))
    blue = Image.new("RGB", (300, 300), (20, 40, 220))
    d = ImageDraw.Draw(blue)
    d.ellipse((50, 50, 250, 250), fill=(240, 240, 240))
    t_red, t_blue = e.text("a red square"), e.text("a white circle on blue")
    v_red, v_blue = e.image(red), e.image(blue)
    assert v_red @ t_red > v_red @ t_blue
    assert v_blue @ t_blue > v_blue @ t_red
