"""HTTP API + static PWA hosting (FastAPI)."""

from __future__ import annotations

import io
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import labels
from .config import Config
from .db import Database
from .embed import Embedder
from .identify import CATEGORIES, Identifier
from .photos import PhotoStore
from .printer import PrinterClient
from .store import Invalid, NotFound, Store
from .vectors import DUPLICATE_MIN_SIM, VectorIndex, agglomerate, consolidation_plan, distinct_names

log = logging.getLogger(__name__)

MAX_UPLOAD = 25 * 1024 * 1024


class ItemIn(BaseModel):
    name: str
    description: str | None = None
    category: str | None = None
    tags: list[str] | str | None = None
    brand: str | None = None
    model: str | None = None
    quantity: int | None = None
    location_note: str | None = None
    source: str | None = None
    source_url: str | None = None
    bin_code: str | None = None
    photo_ids: list[int] = []
    location_photo_id: int | None = None


class ItemPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    tags: list[str] | str | None = None
    brand: str | None = None
    model: str | None = None
    quantity: int | None = None
    location_note: str | None = None
    primary_photo_id: int | None = None
    location_photo_id: int | None = None


class ItemIds(BaseModel):
    item_ids: list[int]
    bin_code: str | None = None
    note: str = ""


class PhotoLink(BaseModel):
    photo_id: int
    primary: bool = False


class BinIn(BaseModel):
    code: str | None = None
    name: str = ""
    location: str = ""
    notes: str = ""
    count: int = 1          # >1 allocates a batch of sequential codes
    print: bool = False     # print a label for each new bin


class BinPatch(BaseModel):
    name: str | None = None
    location: str | None = None
    notes: str | None = None
    photo_id: int | None = None


class PrintReq(BaseModel):
    codes: list[str] = []
    copies: int = 1


def create_app(cfg: Config) -> FastAPI:
    db = Database(cfg.db_path)
    store = Store(db)
    photos = PhotoStore(cfg.photo_dir)
    embedder = Embedder(cfg.model_dir, cfg.model_base_url, cfg.embed_enabled)
    index = VectorIndex(db, photos, embedder)
    identifier = Identifier(cfg.google_vision_api_key, cfg.anthropic_api_key, cfg.claude_model)
    printer = PrinterClient(cfg.printd_url)
    group_names: dict[frozenset, str] = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        _cleanup_orphan_photos(db, photos)
        embedder.start()
        index.start()
        # Kick the indexer once the model has loaded.
        import threading

        def _kick():
            embedder._ready.wait()
            index.poke()
        threading.Thread(target=_kick, daemon=True).start()
        yield
        index.stop()

    app = FastAPI(title="inventory", lifespan=lifespan)
    app.state.store, app.state.index, app.state.embedder = store, index, embedder
    app.state.identifier, app.state.printer, app.state.photos = identifier, printer, photos

    @app.exception_handler(NotFound)
    async def _nf(_: Request, e: NotFound):
        return JSONResponse({"detail": str(e)}, status_code=404)

    @app.exception_handler(Invalid)
    async def _inv(_: Request, e: Invalid):
        return JSONResponse({"detail": str(e)}, status_code=400)

    def base_url(request: Request) -> str:
        return cfg.public_url or str(request.base_url).rstrip("/")

    async def read_upload(f: UploadFile) -> bytes:
        data = await f.read()
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "image too large")
        if not data:
            raise HTTPException(400, "empty upload")
        return data

    def save_photo(data: bytes, kind: str = "item") -> dict:
        try:
            rel, w, h = photos.save(data)
        except Exception as e:  # noqa: BLE001 — PIL raises many types for junk input
            raise HTTPException(400, f"not an image: {e}") from e
        cur = db.conn.execute("INSERT INTO photos (kind, file, width, height) VALUES (?, ?, ?, ?)",
                              (kind, rel, w, h))
        return {"id": cur.lastrowid, "file": rel, "width": w, "height": h}

    # ---- status -----------------------------------------------------------------

    @app.get("/api/status")
    def status(printer_check: bool = Query(False, alias="printer")):
        out: dict[str, Any] = {
            **store.stats(),
            "identify": identifier.status,
            "embedder": embedder.status,
            "categories": CATEGORIES,
        }
        if printer_check:
            out["printer"] = printer.status()
        return out

    # ---- photos -----------------------------------------------------------------

    @app.post("/api/photos")
    async def upload_photo(file: UploadFile = File(...), kind: str = Form("item")):
        if kind not in ("item", "location", "bin"):
            raise HTTPException(400, "bad kind")
        p = save_photo(await read_upload(file), kind)
        return {"id": p["id"], "width": p["width"], "height": p["height"]}

    def _photo_file(photo_id: int) -> str:
        r = db.conn.execute("SELECT file FROM photos WHERE id = ?", (photo_id,)).fetchone()
        if not r:
            raise HTTPException(404, "no such photo")
        return r["file"]

    @app.get("/photos/{photo_id}.jpg")
    def photo(photo_id: int):
        return FileResponse(photos.path(_photo_file(photo_id)), media_type="image/jpeg",
                            headers={"Cache-Control": "public, max-age=31536000, immutable"})

    @app.get("/photos/{photo_id}/thumb.jpg")
    def thumb(photo_id: int):
        return FileResponse(photos.thumb_path(_photo_file(photo_id)), media_type="image/jpeg",
                            headers={"Cache-Control": "public, max-age=31536000, immutable"})

    # ---- identify / search ----------------------------------------------------------

    def _similar(vec, min_sim: float | None, limit: int = 8) -> list[dict]:
        hits = index.search_image(vec, limit=limit, min_sim=min_sim)
        items = {i["id"]: i for i in store.items_by_ids([h[0] for h in hits])}
        return [{**items[iid], "score": round(s, 3)} for iid, s in hits if iid in items]

    @app.post("/api/identify")
    async def identify(file: UploadFile = File(...)):
        """Save the photo (pending until an item claims it) and suggest what it is."""
        p = save_photo(await read_upload(file))
        jpeg = photos.path(p["file"]).read_bytes()
        from starlette.concurrency import run_in_threadpool

        cands, errors = await run_in_threadpool(identifier.identify, jpeg)
        similar: list[dict] = []
        if embedder.ready:
            vec = await run_in_threadpool(index.embed_photo, p["id"], p["file"])
            similar = await run_in_threadpool(_similar, vec, DUPLICATE_MIN_SIM, 4)
        return {
            "photo_id": p["id"],
            "candidates": [c.to_dict() for c in cands],
            "similar": similar,
            "errors": errors,
            "providers": {**identifier.status, "embedder": embedder.status},
        }

    @app.post("/api/search/image")
    async def search_image(file: UploadFile = File(...)):
        if not embedder.ready:
            raise HTTPException(503, f"visual search unavailable ({embedder.status})")
        from PIL import Image, ImageOps

        data = await read_upload(file)
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        from starlette.concurrency import run_in_threadpool

        vec = await run_in_threadpool(embedder.image, img)
        return {"items": await run_in_threadpool(_similar, vec, None, 24)}

    @app.get("/api/search")
    def search(q: str = "", limit: int = 40):
        q = q.strip()
        if not q:
            return {"items": []}
        fts = store.fts_search(q, limit=limit)
        sem = index.search_text(q, limit=limit) if embedder.ready else []
        # Reciprocal-rank fusion: keyword hits and visual/semantic hits on one list.
        scores: dict[int, float] = {}
        why: dict[int, set[str]] = {}
        for rank, iid in enumerate(fts):
            scores[iid] = scores.get(iid, 0) + 1 / (20 + rank)
            why.setdefault(iid, set()).add("text")
        for rank, (iid, _) in enumerate(sem):
            scores[iid] = scores.get(iid, 0) + 0.8 / (20 + rank)
            why.setdefault(iid, set()).add("visual")
        ranked = sorted(scores, key=lambda i: -scores[i])[:limit]
        items = store.items_by_ids(ranked)
        return {"items": [{**i, "match": sorted(why[i["id"]])} for i in items]}

    # ---- items -------------------------------------------------------------------

    @app.get("/api/items")
    def list_items(bin: str | None = None, out: bool | None = None, unbinned: bool = False,
                   limit: int = 500, offset: int = 0):
        bin_id = store.get_bin(bin)["id"] if bin else None
        return {"items": store.list_items(bin_id=bin_id, checked_out=out, unbinned=unbinned,
                                          limit=limit, offset=offset)}

    @app.post("/api/items")
    def create_item(body: ItemIn):
        d = body.model_dump()
        item = store.create_item(**d)
        index.poke()
        return item

    @app.get("/api/items/{item_id}")
    def get_item(item_id: int):
        return store.get_item(item_id, with_detail=True)

    @app.patch("/api/items/{item_id}")
    def patch_item(item_id: int, body: ItemPatch):
        item = store.update_item(item_id, **body.model_dump(exclude_unset=True))
        index.poke()
        return item

    @app.delete("/api/items/{item_id}")
    def delete_item(item_id: int):
        for f in store.delete_item(item_id):
            photos.delete(f)
        return {"ok": True}

    @app.post("/api/items/{item_id}/photos")
    def add_photo(item_id: int, body: PhotoLink):
        item = store.add_photo(item_id, body.photo_id, body.primary)
        index.poke()
        return item

    @app.post("/api/items/move")
    def move(body: ItemIds):
        return {"items": store.move_items(body.item_ids, body.bin_code, body.note)}

    @app.post("/api/items/checkout")
    def checkout(body: ItemIds):
        return {"items": store.check_out(body.item_ids, body.note)}

    @app.post("/api/items/checkin")
    def checkin(body: ItemIds):
        return {"items": store.check_in(body.item_ids, body.bin_code)}

    @app.get("/api/manifest")
    def manifest():
        return store.checkin_manifest()

    # ---- bins ---------------------------------------------------------------------

    @app.get("/api/bins")
    def list_bins():
        return {"bins": store.list_bins()}

    @app.post("/api/bins")
    def create_bins(body: BinIn, request: Request):
        if body.count > 1:
            bins = store.create_bins(body.count)
        else:
            bins = [store.create_bin(body.code, name=body.name, location=body.location, notes=body.notes)]
        printed = None
        if body.print:
            printed = _print_codes([b["code"] for b in bins], 1, base_url(request))
        return {"bins": bins, "printed": printed}

    @app.get("/api/bins/{code}")
    def get_bin(code: str):
        return store.get_bin(code, with_items=True)

    @app.patch("/api/bins/{code}")
    def patch_bin(code: str, body: BinPatch):
        return store.update_bin(code, **body.model_dump(exclude_unset=True))

    @app.delete("/api/bins/{code}")
    def delete_bin(code: str):
        store.delete_bin(code)
        return {"ok": True}

    def _label(code: str, request_base: str):
        b = store.get_bin(code)
        return labels.render_bin_label(b["code"], b["name"], request_base, cfg.label_font)

    @app.get("/api/bins/{code}/label.png")
    def label_png(code: str, request: Request):
        buf = io.BytesIO()
        _label(code, base_url(request)).save(buf, "PNG")
        return Response(buf.getvalue(), media_type="image/png")

    def _print_codes(codes: list[str], copies: int, base: str) -> dict:
        if not 1 <= copies <= 10:
            raise HTTPException(400, "copies must be 1..10")
        imgs = [_label(c, base) for c in codes]  # validate every code before printing any
        results = []
        for code, img in zip(codes, imgs):
            try:
                results.append({"code": code, **printer.print_image(img, copies)})
            except Exception as e:  # noqa: BLE001
                raise HTTPException(502, f"printer error on {code}: {e}") from e
        return {"printed": results}

    @app.post("/api/bins/{code}/print")
    def print_bin(code: str, request: Request, body: PrintReq | None = None):
        return _print_codes([code], (body.copies if body else 1), base_url(request))

    @app.post("/api/print")
    def print_many(body: PrintReq, request: Request):
        if not body.codes:
            raise HTTPException(400, "no codes")
        return _print_codes(body.codes, body.copies, base_url(request))

    # ---- grouping --------------------------------------------------------------------

    @app.get("/api/groups")
    def groups(threshold: float = 0.30, min_size: int = 2, ai_names: bool = False):
        """Semantic clusters of items + a plan to consolidate each into one bin."""
        items_all = {i["id"]: i for i in store.list_items(limit=100_000)}
        iv = index.load() if embedder.ready else None
        clusters: list[list[int]]
        method = "embedding"
        if iv is not None and len(iv.ids) >= 2:
            known = iv.has_image | iv.has_text
            ids = iv.ids[known]
            rows = agglomerate(iv.combined()[known], threshold)
            clusters = [[int(ids[r]) for r in c] for c in rows]
        else:
            method = "category"
            by_cat: dict[str, list[int]] = {}
            for i in items_all.values():
                by_cat.setdefault(i["category"] or "Uncategorised", []).append(i["id"])
            clusters = list(by_cat.values())
        member_lists = [m for c in clusters
                        if len(m := [items_all[i] for i in c if i in items_all]) >= min_size]
        out = [{"name": name, "items": members, **consolidation_plan(members)}
               for name, members in zip(distinct_names(member_lists), member_lists)]
        if ai_names and identifier.claude and out:
            todo = [g for g in out if frozenset(i["id"] for i in g["items"]) not in group_names]
            if todo:
                try:
                    names = identifier.claude.name_groups([[i["name"] for i in g["items"]] for g in todo])
                    for g, n in zip(todo, names):
                        group_names[frozenset(i["id"] for i in g["items"])] = n
                except Exception as e:  # noqa: BLE001
                    log.warning("group naming failed: %s", e)
            for g in out:
                g["name"] = group_names.get(frozenset(i["id"] for i in g["items"]), g["name"])
        # Most actionable first: fragmented groups with the most moves.
        out.sort(key=lambda g: (-(g["fragmentation"] > 1), -len(g["moves"]), -len(g["items"])))
        return {"method": method, "threshold": threshold, "groups": out}

    # ---- PWA -------------------------------------------------------------------------

    web = cfg.web_dir
    if web and (web / "index.html").exists():
        if (web / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=web / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            f = (web / path).resolve()
            if path and f.is_file() and f.is_relative_to(web.resolve()):
                headers = {"Cache-Control": "no-cache"} if f.name in ("sw.js", "manifest.webmanifest") else {}
                return FileResponse(f, headers=headers)
            # Client-side routes (/b/B007, /item/12, …) all serve the app shell.
            return FileResponse(web / "index.html", headers={"Cache-Control": "no-cache"})
    else:
        @app.get("/", include_in_schema=False)
        def no_web():
            return JSONResponse({"detail": "web UI not built; run `npm run build` in web/"}, 404)

    return app


def _cleanup_orphan_photos(db: Database, photos: PhotoStore) -> None:
    """Photos uploaded during an identify that never became an item."""
    rows = db.conn.execute(
        """SELECT id, file FROM photos WHERE item_id IS NULL
           AND id NOT IN (SELECT photo_id FROM bins WHERE photo_id IS NOT NULL)
           AND created_at < strftime('%Y-%m-%dT%H:%M:%SZ','now','-2 days')""").fetchall()
    for r in rows:
        photos.delete(r["file"])
        db.conn.execute("DELETE FROM photos WHERE id = ?", (r["id"],))
    if rows:
        log.info("removed %d orphan photos", len(rows))
