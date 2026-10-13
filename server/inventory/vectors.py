"""Vector index over items (CLIP), semantic search, and grouping suggestions.

Vectors live in SQLite (photo_vectors / item_text_vectors). A background
indexer fills in what's missing, so request handlers never block on the model
except when embedding a *query* photo.
"""

from __future__ import annotations

import logging
import threading
from collections import Counter
from dataclasses import dataclass

import numpy as np

from .db import Database
from .embed import MODEL_ID, Embedder, from_blob, normalize, to_blob
from .photos import PhotoStore

log = logging.getLogger(__name__)

# CLIP cosine similarities are compressed and modality-dependent (text->image
# sits around 0.20-0.32, text->text around 0.80-0.95), so fixed cutoffs don't
# work. Semantic search instead scores each item by how far it stands out from
# the rest of the collection for this query (a z-score), per modality.
SEMANTIC_MIN_Z = 1.6
# "You may already own this": a near-duplicate photo. Unrelated objects on
# plain backgrounds routinely reach 0.75-0.8 with the quantised ViT-B/32.
DUPLICATE_MIN_SIM = 0.86


def _z(s: np.ndarray, mask: np.ndarray) -> np.ndarray:
    z = np.full(s.shape, -np.inf)
    if mask.sum() >= 3:
        v = s[mask]
        z[mask] = (v - v.mean()) / max(float(v.std()), 1e-6)
    return z


def item_text(item: dict) -> str:
    parts = [item["name"]]
    if item.get("category"):
        parts.append(item["category"])
    parts += item.get("tags") or []
    return ", ".join(parts)


@dataclass
class ItemVectors:
    ids: np.ndarray        # (N,) item ids
    image: np.ndarray      # (N, D) mean photo vector, zeros if none
    has_image: np.ndarray  # (N,) bool
    text: np.ndarray       # (N, D)
    has_text: np.ndarray

    def combined(self, text_weight: float = 2.0) -> np.ndarray:
        """Per-item vector for clustering.

        Each modality is centred on the collection mean first: raw CLIP vectors
        share a large common component (everything looks like "a photo of a
        thing in a garage"), which drowns out the differences that matter.
        Text (name/category/tags) is weighted up because it carries the user's
        intent — a lantern and a sleeping bag look nothing alike but are both
        "camping"."""
        def centred(m: np.ndarray, has: np.ndarray) -> np.ndarray:
            if not has.any():
                return np.zeros_like(m)
            return normalize(m - m[has].mean(0)) * has[:, None]
        return normalize(centred(self.image, self.has_image) + text_weight * centred(self.text, self.has_text))


class VectorIndex:
    def __init__(self, db: Database, photos: PhotoStore, embedder: Embedder):
        self.db, self.photos, self.embedder = db, photos, embedder
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._cache: tuple[int, ItemVectors] | None = None
        self._version = 0

    # ---- background indexing ------------------------------------------------

    def start(self) -> None:
        threading.Thread(target=self._run, name="vector-indexer", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def poke(self) -> None:
        """Something changed (new photo, edited item) — index soon."""
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(timeout=30)
            self._wake.clear()
            if not self.embedder.ready:
                continue
            try:
                while self.index_pending(limit=16):
                    pass
            except Exception:  # noqa: BLE001
                log.exception("indexer pass failed")

    def embed_photo(self, photo_id: int, file: str) -> np.ndarray:
        vec = self.embedder.image(self.photos.open(file))
        self.db.conn.execute(
            "INSERT OR REPLACE INTO photo_vectors (photo_id, model, vec) VALUES (?, ?, ?)",
            (photo_id, MODEL_ID, to_blob(vec)))
        self._version += 1
        return vec

    def index_pending(self, limit: int = 16) -> int:
        """Embed up to `limit` missing/stale vectors; returns how many were done."""
        c = self.db.conn
        done = 0
        for r in c.execute(
                """SELECT p.id, p.file FROM photos p LEFT JOIN photo_vectors v ON v.photo_id = p.id
                   WHERE p.kind = 'item' AND p.item_id IS NOT NULL AND (v.photo_id IS NULL OR v.model != ?)
                   LIMIT ?""", (MODEL_ID, limit)).fetchall():
            self.embed_photo(r["id"], r["file"])
            done += 1
        import json
        for r in c.execute(
                """SELECT i.id, i.name, i.category, i.tags, v.text AS vtext, v.model AS vmodel
                   FROM items i LEFT JOIN item_text_vectors v ON v.item_id = i.id""").fetchall():
            if done >= limit:
                break
            text = item_text({"name": r["name"], "category": r["category"], "tags": json.loads(r["tags"])})
            if r["vtext"] == text and r["vmodel"] == MODEL_ID:
                continue
            vec = self.embedder.text(text)
            c.execute("INSERT OR REPLACE INTO item_text_vectors (item_id, model, text, vec) VALUES (?, ?, ?, ?)",
                      (r["id"], MODEL_ID, text, to_blob(vec)))
            self._version += 1
            done += 1
        return done

    # ---- loading --------------------------------------------------------------

    def load(self) -> ItemVectors | None:
        cnt = self.db.conn.execute(
            "SELECT (SELECT COUNT(*) FROM photo_vectors) + (SELECT COUNT(*) FROM item_text_vectors) "
            "+ (SELECT COUNT(*) FROM items) * 1000003").fetchone()[0]
        key = hash((cnt, self._version))
        if self._cache and self._cache[0] == key:
            return self._cache[1]
        c = self.db.conn
        ids = [r[0] for r in c.execute("SELECT id FROM items ORDER BY id")]
        if not ids:
            return None
        pos = {iid: k for k, iid in enumerate(ids)}
        img_sum: dict[int, np.ndarray] = {}
        for r in c.execute("""SELECT p.item_id, v.vec FROM photo_vectors v JOIN photos p ON p.id = v.photo_id
                              WHERE p.item_id IS NOT NULL AND p.kind = 'item' AND v.model = ?""", (MODEL_ID,)):
            v = from_blob(r["vec"])
            img_sum[r["item_id"]] = img_sum.get(r["item_id"], 0) + v
        txt: dict[int, np.ndarray] = {
            r["item_id"]: from_blob(r["vec"]) for r in
            c.execute("SELECT item_id, vec FROM item_text_vectors WHERE model = ?", (MODEL_ID,))}
        dim = next((len(v) for v in [*img_sum.values(), *txt.values()]), 0)
        if not dim:
            return None
        n = len(ids)
        image, text = np.zeros((n, dim), np.float32), np.zeros((n, dim), np.float32)
        has_i, has_t = np.zeros(n, bool), np.zeros(n, bool)
        for iid, v in img_sum.items():
            if iid in pos:
                image[pos[iid]] = normalize(v)
                has_i[pos[iid]] = True
        for iid, v in txt.items():
            if iid in pos:
                text[pos[iid]] = v
                has_t[pos[iid]] = True
        iv = ItemVectors(np.array(ids), image, has_i, text, has_t)
        self._cache = (key, iv)
        return iv

    # ---- queries ----------------------------------------------------------------

    def search_text(self, q: str, limit: int = 15) -> list[tuple[int, float]]:
        """Semantic text query against item photos and item names."""
        iv = self.load() if self.embedder.ready else None
        if iv is None:
            return []
        z_img = _z(iv.image @ self.embedder.text(f"a photo of {q}"), iv.has_image)
        z_txt = _z(iv.text @ self.embedder.text(q), iv.has_text)
        score = np.maximum(z_img, z_txt)
        order = np.argsort(-score)[:limit]
        return [(int(iv.ids[k]), float(score[k])) for k in order if score[k] >= SEMANTIC_MIN_Z]

    def search_image(self, vec: np.ndarray, limit: int = 12, min_sim: float | None = None,
                     exclude: set[int] | None = None) -> list[tuple[int, float]]:
        """Items whose photos look like `vec`, best first.

        min_sim=None ranks the whole collection (search-by-photo, keeping only
        items that stand out); a value keeps only near-duplicates above it."""
        iv = self.load()
        if iv is None:
            return []
        s = np.where(iv.has_image, iv.image @ vec, -1.0)
        keep = s >= min_sim if min_sim is not None else _z(s, iv.has_image) >= 1.0
        out = []
        for k in np.argsort(-s):
            if not keep[k] or len(out) >= limit:
                break
            if exclude and int(iv.ids[k]) in exclude:
                continue
            out.append((int(iv.ids[k]), float(s[k])))
        return out


def agglomerate(vecs: np.ndarray, threshold: float) -> list[list[int]]:
    """Average-linkage agglomerative clustering on cosine similarity.

    Merges the most similar pair of clusters until no pair's mean similarity
    reaches `threshold`. Returns clusters as lists of row indices. Fine for the
    few-thousand-item scale of a garage (numpy-vectorised O(N^2) per merge,
    usually far fewer merges than N)."""
    n = len(vecs)
    if n < 2:
        return [[i] for i in range(n)]
    sim = (vecs @ vecs.T).astype(np.float64)
    np.fill_diagonal(sim, -np.inf)
    size = np.ones(n)
    alive = np.ones(n, bool)
    members: list[list[int]] = [[i] for i in range(n)]
    while True:
        k = int(np.argmax(sim))
        a, b = divmod(k, n)
        if sim[a, b] < threshold:
            break
        # Merge b into a; the average-linkage similarity to every other cluster
        # is the size-weighted mean of the two rows.
        row = (sim[a] * size[a] + sim[b] * size[b]) / (size[a] + size[b])
        sim[a, :] = row
        sim[:, a] = row
        sim[a, a] = -np.inf
        sim[b, :] = -np.inf
        sim[:, b] = -np.inf
        size[a] += size[b]
        alive[b] = False
        members[a] += members[b]
        members[b] = []
    return [m for i, m in enumerate(members) if alive[i]]


def describe_group(items: list[dict]) -> str:
    cats = Counter(i["category"] for i in items if i.get("category"))
    tags = Counter(t for i in items for t in i.get("tags") or [])
    if tags:
        top_tag, n = tags.most_common(1)[0]
        if n >= max(2, len(items) * 0.6):
            return top_tag.title()
    if cats:
        return cats.most_common(1)[0][0]
    return items[0]["name"]


def distinct_names(groups: list[list[dict]]) -> list[str]:
    """describe_group for each group, disambiguating repeats ("Camping" twice ->
    "Camping: light" / "Camping: sleep") with each group's own most common
    secondary tag, falling back to its first item's name."""
    names = [describe_group(g) for g in groups]
    counts = Counter(names)
    out = []
    for name, items in zip(names, groups):
        if counts[name] > 1:
            tags = Counter(t for i in items for t in i.get("tags") or [] if t.lower() != name.lower())
            extra = tags.most_common(1)[0][0] if tags else items[0]["name"]
            name = f"{name}: {extra}"
        out.append(name)
    return out


def consolidation_plan(items: list[dict]) -> dict:
    """Pick the bin already holding most of the group; everything else moves there."""
    bins = Counter(i["bin_code"] for i in items if i.get("bin_code"))
    if bins:
        target = sorted(bins.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    else:
        target = None
    moves = [i["id"] for i in items if i.get("bin_code") != target]
    return {
        "target_bin": target,
        "bins": dict(sorted(bins.items())),
        "unbinned": sum(1 for i in items if not i.get("bin_code")),
        "moves": moves,
        "fragmentation": len(bins) + (1 if any(not i.get("bin_code") for i in items) else 0),
    }
