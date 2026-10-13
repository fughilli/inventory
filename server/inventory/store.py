"""Domain operations over the database: items, bins, binning, check-out/in.

Everything the HTTP layer does goes through here, so it is directly unit-tested.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable

from .db import Database

BIN_CODE_RE = re.compile(r"^B(\d{3,})$")

ITEM_FIELDS = ("name", "description", "category", "tags", "brand", "model", "quantity",
               "location_note", "source", "source_url")
BIN_FIELDS = ("name", "location", "notes")


class NotFound(LookupError):
    pass


class Invalid(ValueError):
    pass


def normalize_bin_code(code: str) -> str:
    """'b7', 'B007', ' 7 ' -> 'B007' (3+ digits, grows past 999)."""
    s = code.strip().upper()
    if s.startswith("B"):
        s = s[1:]
    if not s.isdigit():
        raise Invalid(f"not a bin code: {code!r}")
    return f"B{int(s):03d}"


def _tags(v: Any) -> str:
    if isinstance(v, str):
        v = [t for t in re.split(r"[,\n]", v)]
    tags: list[str] = []
    for t in v or []:
        t = str(t).strip().lower()
        if t and t not in tags:
            tags.append(t)
    return json.dumps(tags)


def item_row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["tags"] = json.loads(d.get("tags") or "[]")
    d["checked_out"] = d.get("checked_out_at") is not None
    return d


@dataclass
class Store:
    db: Database

    # ---- bins ---------------------------------------------------------------

    def next_bin_code(self) -> str:
        nums = [int(m.group(1)) for (c,) in self.db.conn.execute("SELECT code FROM bins")
                if (m := BIN_CODE_RE.match(c))]
        return f"B{(max(nums, default=0) + 1):03d}"

    def create_bin(self, code: str | None = None, **fields: Any) -> dict:
        with self.db.tx() as c:
            code = normalize_bin_code(code) if code else self.next_bin_code()
            if c.execute("SELECT 1 FROM bins WHERE code = ?", (code,)).fetchone():
                raise Invalid(f"bin {code} already exists")
            vals = {k: str(fields.get(k) or "") for k in BIN_FIELDS}
            c.execute("INSERT INTO bins (code, name, location, notes) VALUES (?, ?, ?, ?)",
                      (code, vals["name"], vals["location"], vals["notes"]))
        return self.get_bin(code)

    def create_bins(self, count: int) -> list[dict]:
        if not 1 <= count <= 100:
            raise Invalid("count must be 1..100")
        return [self.create_bin() for _ in range(count)]

    def _bin_id(self, code: str) -> int:
        r = self.db.conn.execute("SELECT id FROM bins WHERE code = ?", (normalize_bin_code(code),)).fetchone()
        if not r:
            raise NotFound(f"no bin {code}")
        return r["id"]

    def get_bin(self, code: str, with_items: bool = False) -> dict:
        r = self.db.conn.execute(
            """SELECT b.*, COUNT(i.id) AS item_count,
                      SUM(i.checked_out_at IS NOT NULL) AS out_count
               FROM bins b LEFT JOIN items i ON i.bin_id = b.id
               WHERE b.code = ? GROUP BY b.id""", (normalize_bin_code(code),)).fetchone()
        if not r:
            raise NotFound(f"no bin {code}")
        d = dict(r)
        d["out_count"] = d["out_count"] or 0
        if with_items:
            d["items"] = self.list_items(bin_id=d["id"])
        return d

    def list_bins(self) -> list[dict]:
        rows = self.db.conn.execute(
            """SELECT b.*, COUNT(i.id) AS item_count,
                      COALESCE(SUM(i.checked_out_at IS NOT NULL), 0) AS out_count,
                      (SELECT primary_photo_id FROM items WHERE bin_id = b.id
                         AND primary_photo_id IS NOT NULL ORDER BY updated_at DESC LIMIT 1) AS cover_photo_id
               FROM bins b LEFT JOIN items i ON i.bin_id = b.id
               GROUP BY b.id ORDER BY b.code""").fetchall()
        return [dict(r) for r in rows]

    def update_bin(self, code: str, **fields: Any) -> dict:
        sets = {k: str(v) for k, v in fields.items() if k in BIN_FIELDS and v is not None}
        if "photo_id" in fields:
            sets["photo_id"] = fields["photo_id"]
        bid = self._bin_id(code)
        if sets:
            cols = ", ".join(f"{k} = ?" for k in sets)
            with self.db.tx() as c:
                c.execute(f"UPDATE bins SET {cols}, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id = ?",
                          (*sets.values(), bid))
        return self.get_bin(code)

    def delete_bin(self, code: str) -> None:
        bid = self._bin_id(code)
        with self.db.tx() as c:
            n = c.execute("SELECT COUNT(*) FROM items WHERE bin_id = ?", (bid,)).fetchone()[0]
            if n:
                raise Invalid(f"bin {code} still holds {n} item(s); move them first")
            c.execute("DELETE FROM bins WHERE id = ?", (bid,))

    # ---- items --------------------------------------------------------------

    _ITEM_SELECT = """
        SELECT i.*, b.code AS bin_code, b.name AS bin_name, b.location AS bin_location
        FROM items i LEFT JOIN bins b ON b.id = i.bin_id
    """

    def get_item(self, item_id: int, with_detail: bool = False) -> dict:
        r = self.db.conn.execute(self._ITEM_SELECT + " WHERE i.id = ?", (item_id,)).fetchone()
        if not r:
            raise NotFound(f"no item {item_id}")
        d = item_row(r)
        if with_detail:
            d["photos"] = [dict(p) for p in self.db.conn.execute(
                "SELECT id, kind, width, height, created_at FROM photos WHERE item_id = ? ORDER BY id",
                (item_id,))]
            d["events"] = [dict(e) for e in self.db.conn.execute(
                """SELECT e.kind, e.note, e.at, b.code AS bin_code FROM events e
                   LEFT JOIN bins b ON b.id = e.bin_id WHERE e.item_id = ? ORDER BY e.id DESC LIMIT 50""",
                (item_id,))]
        return d

    def items_by_ids(self, ids: Iterable[int]) -> list[dict]:
        ids = list(ids)
        if not ids:
            return []
        q = self._ITEM_SELECT + f" WHERE i.id IN ({','.join('?' * len(ids))})"
        by_id = {r["id"]: item_row(r) for r in self.db.conn.execute(q, ids)}
        return [by_id[i] for i in ids if i in by_id]

    def list_items(self, bin_id: int | None = None, checked_out: bool | None = None,
                   unbinned: bool = False, limit: int = 500, offset: int = 0) -> list[dict]:
        where, args = [], []
        if bin_id is not None:
            where.append("i.bin_id = ?")
            args.append(bin_id)
        if unbinned:
            where.append("i.bin_id IS NULL")
        if checked_out is not None:
            where.append("i.checked_out_at IS NOT NULL" if checked_out else "i.checked_out_at IS NULL")
        q = self._ITEM_SELECT + (" WHERE " + " AND ".join(where) if where else "")
        q += " ORDER BY i.name COLLATE NOCASE LIMIT ? OFFSET ?"
        return [item_row(r) for r in self.db.conn.execute(q, (*args, limit, offset))]

    def create_item(self, name: str, bin_code: str | None = None, photo_ids: list[int] | None = None,
                    location_photo_id: int | None = None, **fields: Any) -> dict:
        name = (name or "").strip()
        if not name:
            raise Invalid("name is required")
        vals = {k: fields.get(k) for k in ITEM_FIELDS if k != "name" and fields.get(k) is not None}
        if "tags" in vals:
            vals["tags"] = _tags(vals["tags"])
        if "quantity" in vals:
            vals["quantity"] = max(1, int(vals["quantity"]))
        bin_id = self._bin_id(bin_code) if bin_code else None
        photo_ids = photo_ids or []
        with self.db.tx() as c:
            cols = ["name", "bin_id", "primary_photo_id", "location_photo_id", *vals]
            cur = c.execute(
                f"INSERT INTO items ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                (name, bin_id, photo_ids[0] if photo_ids else None, location_photo_id, *vals.values()))
            item_id = cur.lastrowid
            for pid in photo_ids:
                c.execute("UPDATE photos SET item_id = ?, kind = 'item' WHERE id = ?", (item_id, pid))
            if location_photo_id:
                c.execute("UPDATE photos SET item_id = ?, kind = 'location' WHERE id = ?",
                          (item_id, location_photo_id))
            c.execute("INSERT INTO events (item_id, bin_id, kind) VALUES (?, ?, 'created')", (item_id, bin_id))
        return self.get_item(item_id)

    def update_item(self, item_id: int, **fields: Any) -> dict:
        self.get_item(item_id)
        sets: dict[str, Any] = {}
        for k in ITEM_FIELDS:
            if k in fields and fields[k] is not None:
                v = fields[k]
                if k == "tags":
                    v = _tags(v)
                elif k == "quantity":
                    v = max(1, int(v))
                elif k == "name":
                    v = str(v).strip()
                    if not v:
                        raise Invalid("name is required")
                sets[k] = v
        for k in ("primary_photo_id", "location_photo_id"):
            if k in fields:
                sets[k] = fields[k]
        with self.db.tx() as c:
            if sets:
                cols = ", ".join(f"{k} = ?" for k in sets)
                c.execute(f"UPDATE items SET {cols}, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id = ?",
                          (*sets.values(), item_id))
            if fields.get("location_photo_id"):
                c.execute("UPDATE photos SET item_id = ?, kind = 'location' WHERE id = ?",
                          (item_id, fields["location_photo_id"]))
        return self.get_item(item_id)

    def add_photo(self, item_id: int, photo_id: int, make_primary: bool = False) -> dict:
        item = self.get_item(item_id)
        with self.db.tx() as c:
            c.execute("UPDATE photos SET item_id = ?, kind = 'item' WHERE id = ?", (item_id, photo_id))
            if make_primary or not item["primary_photo_id"]:
                c.execute("UPDATE items SET primary_photo_id = ? WHERE id = ?", (photo_id, item_id))
        return self.get_item(item_id)

    def delete_item(self, item_id: int) -> list[str]:
        """Deletes the item; returns photo files to remove from disk."""
        self.get_item(item_id)
        with self.db.tx() as c:
            files = [r["file"] for r in c.execute("SELECT file FROM photos WHERE item_id = ?", (item_id,))]
            c.execute("DELETE FROM items WHERE id = ?", (item_id,))
        return files

    # ---- binning / check-out ------------------------------------------------

    def move_items(self, item_ids: list[int], bin_code: str | None, note: str = "") -> list[dict]:
        """Put items into a bin (or take them out of any bin with bin_code=None).

        Placing an item counts as returning it, so this also clears check-out."""
        bin_id = self._bin_id(bin_code) if bin_code else None
        with self.db.tx() as c:
            for iid in item_ids:
                r = c.execute("SELECT bin_id FROM items WHERE id = ?", (iid,)).fetchone()
                if not r:
                    raise NotFound(f"no item {iid}")
                c.execute("""UPDATE items SET bin_id = ?, checked_out_at = NULL, checked_out_note = '',
                             updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id = ?""", (bin_id, iid))
                kind = "binned" if bin_id else "unbinned"
                if r["bin_id"] and bin_id and r["bin_id"] != bin_id:
                    kind = "moved"
                c.execute("INSERT INTO events (item_id, bin_id, kind, note) VALUES (?, ?, ?, ?)",
                          (iid, bin_id, kind, note))
        return self.items_by_ids(item_ids)

    def check_out(self, item_ids: list[int], note: str = "") -> list[dict]:
        with self.db.tx() as c:
            for iid in item_ids:
                r = c.execute("SELECT bin_id FROM items WHERE id = ?", (iid,)).fetchone()
                if not r:
                    raise NotFound(f"no item {iid}")
                c.execute("""UPDATE items SET checked_out_at = strftime('%Y-%m-%dT%H:%M:%SZ','now'),
                             checked_out_note = ? WHERE id = ? AND checked_out_at IS NULL""", (note, iid))
                c.execute("INSERT INTO events (item_id, bin_id, kind, note) VALUES (?, ?, 'checked_out', ?)",
                          (iid, r["bin_id"], note))
        return self.items_by_ids(item_ids)

    def check_in(self, item_ids: list[int], bin_code: str | None = None) -> list[dict]:
        """Return items home — or to a different bin if `bin_code` is given."""
        if bin_code:
            return self.move_items(item_ids, bin_code, note="checked in")
        with self.db.tx() as c:
            for iid in item_ids:
                r = c.execute("SELECT bin_id FROM items WHERE id = ?", (iid,)).fetchone()
                if not r:
                    raise NotFound(f"no item {iid}")
                c.execute("UPDATE items SET checked_out_at = NULL, checked_out_note = '' WHERE id = ?", (iid,))
                c.execute("INSERT INTO events (item_id, bin_id, kind) VALUES (?, ?, 'checked_in')",
                          (iid, r["bin_id"]))
        return self.items_by_ids(item_ids)

    def checkin_manifest(self) -> dict:
        """Checked-out items grouped by the bin each must go back to."""
        out = self.list_items(checked_out=True, limit=10_000)
        groups: dict[str, dict] = {}
        for it in sorted(out, key=lambda i: (i["bin_code"] or "~", i["name"].lower())):
            key = it["bin_code"] or ""
            g = groups.setdefault(key, {
                "bin_code": it["bin_code"], "bin_name": it["bin_name"],
                "bin_location": it["bin_location"], "location_note": None, "items": []})
            g["items"].append(it)
        return {"count": len(out), "groups": list(groups.values())}

    # ---- text search ----------------------------------------------------------

    def fts_search(self, q: str, limit: int = 50) -> list[int]:
        terms = re.findall(r"\w+", q.lower())
        if not terms:
            return []
        # Prefix-match every term so typing "screwd" finds "screwdriver".
        match = " ".join(f'"{t}"*' for t in terms)
        try:
            rows = self.db.conn.execute(
                "SELECT rowid FROM items_fts WHERE items_fts MATCH ? ORDER BY bm25(items_fts, 10, 2, 3, 4, 3, 3) LIMIT ?",
                (match, limit)).fetchall()
        except sqlite3.OperationalError:
            return []
        ids = [r[0] for r in rows]
        # Bin codes/names also count: "B004" or "camping" bin name.
        bin_rows = self.db.conn.execute(
            """SELECT i.id FROM items i JOIN bins b ON b.id = i.bin_id
               WHERE b.code = ? OR b.name LIKE ? LIMIT ?""",
            (q.strip().upper(), f"%{q.strip()}%", limit)).fetchall()
        ids += [r[0] for r in bin_rows if r[0] not in ids]
        return ids

    def stats(self) -> dict:
        c = self.db.conn
        return {
            "items": c.execute("SELECT COUNT(*) FROM items").fetchone()[0],
            "bins": c.execute("SELECT COUNT(*) FROM bins").fetchone()[0],
            "checked_out": c.execute("SELECT COUNT(*) FROM items WHERE checked_out_at IS NOT NULL").fetchone()[0],
            "unbinned": c.execute("SELECT COUNT(*) FROM items WHERE bin_id IS NULL").fetchone()[0],
        }
