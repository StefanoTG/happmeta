"""
Config loader for SubProxy.

Reads JSON config from disk and exposes a singleton accessor.
Config path can be overridden via SUBPROXY_CONFIG env var.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

DEFAULT_CONFIG_PATH = "/opt/subproxy/config/config.json"


class Config:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or os.environ.get("SUBPROXY_CONFIG", DEFAULT_CONFIG_PATH)
        self._data: Dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        p = Path(self.path)
        if not p.exists():
            raise FileNotFoundError(f"Config file not found: {self.path}")
        with p.open("r", encoding="utf-8") as f:
            self._data = json.load(f)

    # ------- accessors -------
    @property
    def panel(self) -> Dict[str, Any]:
        return self._data["panel"]

    @property
    def middleware(self) -> Dict[str, Any]:
        return self._data["middleware"]

    @property
    def telegram(self) -> Dict[str, Any]:
        return self._data["telegram"]

    @property
    def paths(self) -> Dict[str, Any]:
        return self._data["paths"]

    @property
    def panel_base_url(self) -> str:
        scheme = self.panel.get("scheme", "https")
        host = self.panel["host"]
        port = self.panel.get("port")
        if port and not (
            (scheme == "https" and int(port) == 443)
            or (scheme == "http" and int(port) == 80)
        ):
            return f"{scheme}://{host}:{port}"
        return f"{scheme}://{host}"


_config_instance: Config | None = None


def get_config() -> Config:
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance


def reload_config() -> Config:
    global _config_instance
    _config_instance = Config()
    return _config_instance
