"""SQLite storage: schema, migrations, and a per-thread connection helper.

Plain sqlite3 (no ORM). One database file under the data dir, WAL mode so the
background embedder can write while requests read.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

# Each entry is applied once, in order; the index+1 is stored in user_version.
MIGRATIONS: list[str] = [
    """
    CREATE TABLE bins (
        id          INTEGER PRIMARY KEY,
        code        TEXT NOT NULL UNIQUE,          -- human-readable ID printed on the label, e.g. B007
        name        TEXT NOT NULL DEFAULT '',
        location    TEXT NOT NULL DEFAULT '',      -- where the bin lives (shelf / rack / area)
        notes       TEXT NOT NULL DEFAULT '',
        photo_id    INTEGER REFERENCES photos(id) ON DELETE SET NULL,
        created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
    );

    CREATE TABLE items (
        id              INTEGER PRIMARY KEY,
        name            TEXT NOT NULL,
        description     TEXT NOT NULL DEFAULT '',
        category        TEXT NOT NULL DEFAULT '',
        tags            TEXT NOT NULL DEFAULT '[]',   -- JSON array of strings
        brand           TEXT NOT NULL DEFAULT '',
        model           TEXT NOT NULL DEFAULT '',
        quantity        INTEGER NOT NULL DEFAULT 1,
        -- The item's HOME bin. It stays set while the item is checked out, so the
        -- check-in manifest knows where it goes back.
        bin_id          INTEGER REFERENCES bins(id) ON DELETE SET NULL,
        -- For things that don't live in a bin: free text + a photo of the spot.
        location_note   TEXT NOT NULL DEFAULT '',
        location_photo_id INTEGER REFERENCES photos(id) ON DELETE SET NULL,
        primary_photo_id  INTEGER REFERENCES photos(id) ON DELETE SET NULL,
        checked_out_at  TEXT,                          -- NULL = in its home
        checked_out_note TEXT NOT NULL DEFAULT '',
        source          TEXT NOT NULL DEFAULT 'manual',  -- which identifier named it
        source_url      TEXT NOT NULL DEFAULT '',
        created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
    );
    CREATE INDEX items_bin ON items(bin_id);
    CREATE INDEX items_out ON items(checked_out_at) WHERE checked_out_at IS NOT NULL;

    CREATE TABLE photos (
        id          INTEGER PRIMARY KEY,
        item_id     INTEGER REFERENCES items(id) ON DELETE CASCADE,  -- NULL until attached
        kind        TEXT NOT NULL DEFAULT 'item',  -- item | location | bin
        file        TEXT NOT NULL,                 -- relative to the photo dir
        width       INTEGER NOT NULL,
        height      INTEGER NOT NULL,
        created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
    );
    CREATE INDEX photos_item ON photos(item_id);

    -- CLIP image embedding per photo (item photos only).
    CREATE TABLE photo_vectors (
        photo_id    INTEGER PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
        model       TEXT NOT NULL,
        vec         BLOB NOT NULL                  -- float32, L2-normalised
    );

    -- CLIP text embedding of the item's name/category/tags. `text` is what was
    -- embedded, so edits are detected and re-embedded.
    CREATE TABLE item_text_vectors (
        item_id     INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
        model       TEXT NOT NULL,
        text        TEXT NOT NULL,
        vec         BLOB NOT NULL
    );

    -- Append-only history: binned, moved, checked out/in, created.
    CREATE TABLE events (
        id          INTEGER PRIMARY KEY,
        item_id     INTEGER REFERENCES items(id) ON DELETE CASCADE,
        bin_id      INTEGER REFERENCES bins(id) ON DELETE SET NULL,
        kind        TEXT NOT NULL,
        note        TEXT NOT NULL DEFAULT '',
        at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
    );
    CREATE INDEX events_item ON events(item_id);

    CREATE VIRTUAL TABLE items_fts USING fts5(
        name, description, category, tags, brand, model,
        content='items', content_rowid='id', tokenize='porter unicode61'
    );
    CREATE TRIGGER items_ai AFTER INSERT ON items BEGIN
        INSERT INTO items_fts(rowid, name, description, category, tags, brand, model)
        VALUES (new.id, new.name, new.description, new.category, new.tags, new.brand, new.model);
    END;
    CREATE TRIGGER items_ad AFTER DELETE ON items BEGIN
        INSERT INTO items_fts(items_fts, rowid, name, description, category, tags, brand, model)
        VALUES ('delete', old.id, old.name, old.description, old.category, old.tags, old.brand, old.model);
    END;
    CREATE TRIGGER items_au AFTER UPDATE OF name, description, category, tags, brand, model ON items BEGIN
        INSERT INTO items_fts(items_fts, rowid, name, description, category, tags, brand, model)
        VALUES ('delete', old.id, old.name, old.description, old.category, old.tags, old.brand, old.model);
        INSERT INTO items_fts(rowid, name, description, category, tags, brand, model)
        VALUES (new.id, new.name, new.description, new.category, new.tags, new.brand, new.model);
    END;
    """,
]


class Database:
    """Owns the db path; hands out one connection per thread."""

    def __init__(self, path: Path):
        self.path = path
        self._local = threading.local()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = self._connect()
            self._local.conn = c
        return c

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """An immediate (write-locking) transaction."""
        c = self.conn
        c.execute("BEGIN IMMEDIATE")
        try:
            yield c
        except BaseException:
            c.execute("ROLLBACK")
            raise
        else:
            c.execute("COMMIT")

    def migrate(self) -> None:
        c = self._connect()
        try:
            version = c.execute("PRAGMA user_version").fetchone()[0]
            for i, sql in enumerate(MIGRATIONS[version:], start=version + 1):
                c.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {i};\nCOMMIT;")
        finally:
            c.close()
