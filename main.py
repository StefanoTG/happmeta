"""
Top-level entrypoint to run the FastAPI app directly (for development).

In production, systemd runs uvicorn against `app.main:app`.
"""
from __future__ import annotations

import uvicorn

from app.config import get_config


def main() -> None:
    cfg = get_config()
    uvicorn.run(
        "app.main:app",
        host=cfg.middleware.get("host", "0.0.0.0"),
        port=int(cfg.middleware.get("port", 8080)),
        log_level=cfg.middleware.get("log_level", "info").lower(),
    )


if __name__ == "__main__":
    main()
