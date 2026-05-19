"""
SQLite data access layer for SubProxy.

All metadata headers and node-rename rules live here. The Telegram
bot and the FastAPI proxy share this same database.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    value      TEXT NOT NULL,
    enabled    INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS node_rules (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_type  TEXT NOT NULL,
    pattern    TEXT,
    replacement TEXT NOT NULL,
    enabled    INTEGER NOT NULL DEFAULT 1,
    priority   INTEGER NOT NULL DEFAULT 100,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self):
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.executescript(SCHEMA)

    # ---------------- metadata ----------------
    def list_metadata(self, include_disabled: bool = True) -> List[Dict[str, Any]]:
        q = "SELECT * FROM metadata"
        if not include_disabled:
            q += " WHERE enabled = 1"
        q += " ORDER BY name"
        with self._conn() as c:
            return [dict(r) for r in c.execute(q).fetchall()]

    def get_metadata(self, name: str) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            r = c.execute("SELECT * FROM metadata WHERE name = ?", (name,)).fetchone()
            return dict(r) if r else None

    def upsert_metadata(self, name: str, value: str, enabled: bool = True) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT INTO metadata (name, value, enabled) VALUES (?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                       value=excluded.value,
                       enabled=excluded.enabled,
                       updated_at=CURRENT_TIMESTAMP""",
                (name.strip().lower(), value, 1 if enabled else 0),
            )

    def set_metadata_enabled(self, name: str, enabled: bool) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE metadata SET enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE name = ?",
                (1 if enabled else 0, name),
            )

    def delete_metadata(self, name: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM metadata WHERE name = ?", (name,))

    # ---------------- node rules ----------------
    def list_node_rules(self, only_enabled: bool = False) -> List[Dict[str, Any]]:
        q = "SELECT * FROM node_rules"
        if only_enabled:
            q += " WHERE enabled = 1"
        q += " ORDER BY priority ASC, id ASC"
        with self._conn() as c:
            return [dict(r) for r in c.execute(q).fetchall()]

    def add_node_rule(self, rule_type: str, replacement: str,
                      pattern: Optional[str] = None,
                      priority: int = 100, enabled: bool = True) -> int:
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO node_rules (rule_type, pattern, replacement, priority, enabled)
                   VALUES (?, ?, ?, ?, ?)""",
                (rule_type, pattern, replacement, priority, 1 if enabled else 0),
            )
            return cur.lastrowid

    def delete_node_rule(self, rule_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM node_rules WHERE id = ?", (rule_id,))

    def set_node_rule_enabled(self, rule_id: int, enabled: bool) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE node_rules SET enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (1 if enabled else 0, rule_id),
            )

    # ---------------- settings ----------------
    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._conn() as c:
            r = c.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return r["value"] if r else default

    def set_setting(self, key: str, value: str) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT INTO settings (key, value) VALUES (?, ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (key, value),
            )

    # ---------------- seed defaults ----------------
    def seed_defaults(self, items: Iterable[tuple[str, str]]) -> None:
        """Insert default metadata rows if table is empty."""
        with self._conn() as c:
            n = c.execute("SELECT COUNT(*) AS n FROM metadata").fetchone()["n"]
            if n > 0:
                return
            c.executemany(
                "INSERT INTO metadata (name, value, enabled) VALUES (?, ?, 1)",
                list(items),
            )


_db_instance: Optional[Database] = None


def get_db(path: Optional[str] = None) -> Database:
    global _db_instance
    if _db_instance is None:
        if not path:
            from .config import get_config
            path = get_config().paths["database"]
        _db_instance = Database(path)
    return _db_instance
