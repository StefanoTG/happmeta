"""
In-memory cache for hot DB reads (metadata + node rules).

We refresh from SQLite only when the database's `data_version` pragma
changes — which is updated by SQLite itself on any write from any
process (including the Telegram bot). That means edits made via the bot
take effect on the next request without explicit reloads, while busy
request bursts don't pound the DB.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List

from .database import Database

# Hard cap so we always re-check the DB at least this often even if a
# write somehow doesn't bump data_version.
_MAX_AGE_SECONDS = 2.0


class DataCache:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._lock = threading.Lock()
        self._version: int = -1
        self._last_check: float = 0.0
        self._metadata: List[Dict[str, Any]] = []
        self._enabled_rules: List[Dict[str, Any]] = []

    def _maybe_refresh(self) -> None:
        now = time.monotonic()
        if now - self._last_check < _MAX_AGE_SECONDS and self._version != -1:
            return
        with self._lock:
            if now - self._last_check < _MAX_AGE_SECONDS and self._version != -1:
                return
            current = self._db.data_version()
            if current != self._version:
                self._metadata = self._db.list_metadata(include_disabled=True)
                self._enabled_rules = self._db.list_node_rules(only_enabled=True)
                self._version = current
            self._last_check = now

    def metadata(self) -> List[Dict[str, Any]]:
        self._maybe_refresh()
        return self._metadata

    def enabled_node_rules(self) -> List[Dict[str, Any]]:
        self._maybe_refresh()
        return self._enabled_rules


_cache: DataCache | None = None


def get_cache() -> DataCache:
    global _cache
    if _cache is None:
        from .database import get_db
        _cache = DataCache(get_db())
    return _cache
