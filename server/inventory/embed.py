"""CLIP (ViT-B/32) image + text embeddings via ONNX Runtime.

Image and text vectors share one space, which buys three features at once:
  * search by photo  (image -> image) — "where's the other one of these?"
  * text search over photos (text -> image) — finds "red tent" even if the item
    was named "Coleman Sundome 4"
  * semantic grouping (clustering item vectors) for defragmenting storage.

The quantised Xenova export (~150 MB total) is fetched on first start into the
data dir; until it's ready (or if onnxruntime isn't installed) `ready` is False
and every caller degrades gracefully to text-only behaviour.
"""

from __future__ import annotations

import logging
import threading
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

log = logging.getLogger(__name__)

MODEL_ID = "clip-vit-b32-q"
FILES = {
    "vision.onnx": "onnx/vision_model_quantized.onnx",
    "text.onnx": "onnx/text_model_quantized.onnx",
    "tokenizer.json": "tokenizer.json",
}
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
SIZE = 224
MAX_TOKENS = 77


def to_blob(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def from_blob(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


def normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.maximum(n, 1e-12)


def preprocess(img: Image.Image) -> np.ndarray:
    """CLIPFeatureExtractor: shortest edge -> 224 (bicubic), center crop, normalise."""
    img = img.convert("RGB")
    w, h = img.size
    s = SIZE / min(w, h)
    img = img.resize((max(SIZE, round(w * s)), max(SIZE, round(h * s))), Image.Resampling.BICUBIC)
    w, h = img.size
    left, top = (w - SIZE) // 2, (h - SIZE) // 2
    img = img.crop((left, top, left + SIZE, top + SIZE))
    x = (np.asarray(img, dtype=np.float32) / 255.0 - MEAN) / STD
    return x.transpose(2, 0, 1)[None]  # 1x3x224x224


class Embedder:
    def __init__(self, model_dir: Path, base_url: str, enabled: bool = True):
        self.model_dir = model_dir
        self.base_url = base_url
        self.enabled = enabled
        self.error: str | None = None
        self._ready = threading.Event()
        self._lock = threading.Lock()  # ORT sessions are thread-safe, tokenizer setup isn't
        self._vision = self._text = self._tok = None

    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    @property
    def status(self) -> str:
        if not self.enabled:
            return "disabled"
        if self.ready:
            return "ready"
        return f"error: {self.error}" if self.error else "loading"

    def start(self) -> None:
        if self.enabled:
            threading.Thread(target=self._load, name="embedder-load", daemon=True).start()

    def _download(self) -> None:
        self.model_dir.mkdir(parents=True, exist_ok=True)
        for local, remote in FILES.items():
            dst = self.model_dir / local
            if dst.exists():
                continue
            url = f"{self.base_url}/{remote}"
            log.info("downloading %s", url)
            tmp = dst.with_suffix(".part")
            with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
            tmp.rename(dst)

    def _load(self) -> None:
        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer

            self._download()
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 2  # leave cores for the web server
            prov = ["CPUExecutionProvider"]
            self._vision = ort.InferenceSession(str(self.model_dir / "vision.onnx"), opts, providers=prov)
            self._text = ort.InferenceSession(str(self.model_dir / "text.onnx"), opts, providers=prov)
            tok = Tokenizer.from_file(str(self.model_dir / "tokenizer.json"))
            tok.enable_truncation(MAX_TOKENS)
            self._tok = tok
            self._ready.set()
            log.info("embedder ready")
        except Exception as e:  # noqa: BLE001 — degrade, never crash the server
            self.error = f"{type(e).__name__}: {e}"
            log.warning("embedder unavailable: %s", self.error)

    def image(self, img: Image.Image) -> np.ndarray:
        assert self._vision is not None
        out = self._vision.run(["image_embeds"], {"pixel_values": preprocess(img)})[0][0]
        return normalize(out.astype(np.float32))

    def text(self, s: str) -> np.ndarray:
        assert self._text is not None and self._tok is not None
        with self._lock:
            ids = self._tok.encode(s.lower()).ids
        out = self._text.run(["text_embeds"], {"input_ids": np.array([ids], dtype=np.int64)})[0][0]
        return normalize(out.astype(np.float32))
