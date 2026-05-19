"""
FastAPI entrypoint for the SubProxy middleware.

Mounts a catch-all route that forwards every request to the upstream
Pasarguard panel and rewrites the response on the fly.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .config import get_config
from .database import get_db
from .logger import setup_logger
from .proxy import forward_subscription

cfg = get_config()
log = setup_logger(
    "subproxy",
    log_file=cfg.paths.get("log_file"),
    level=cfg.middleware.get("log_level", "INFO"),
)

# Seed sensible defaults the first time the database is created.
db = get_db()
db.seed_defaults([
    ("profile-title", "Premium VPN", ),
    ("profile-update-interval", "12"),
    ("support-url", f"https://{cfg.middleware.get('public_domain', 'example.com')}/support"),
])

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="SubProxy Middleware",
    description="Transparent subscription proxy for Pasarguard",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_RATE = f"{cfg.middleware.get('rate_limit_per_minute', 120)}/minute"


@app.get("/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse({"ok": True})


@app.api_route("/{path:path}", methods=["GET", "HEAD"])
@limiter.limit(_RATE)
async def catch_all(request: Request, path: str) -> Response:
    return await forward_subscription(request, path)
