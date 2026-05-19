"""
HTTP proxy logic. Forwards subscription requests to the real Pasarguard
panel, then rewrites headers + body before returning to the client.

A single httpx.AsyncClient is reused across all requests so TCP+TLS
connections stay warm, which makes subsequent subscription updates
practically instant.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import Response

from .cache import get_cache
from .config import get_config
from .modifier import build_response_headers, modify_body

log = logging.getLogger("subproxy")


# Headers we don't want to leak from the client to the upstream panel.
_STRIP_REQUEST_HEADERS = {
    "host",
    "content-length",
    "connection",
    "keep-alive",
    "proxy-authorization",
    "proxy-connection",
    "te",
    "upgrade",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-real-ip",
    # Force identity encoding from upstream (httpx doesn't decode br/zstd).
    "accept-encoding",
}


# ----------------------------------------------------------------------
# Shared client (created once at startup)
# ----------------------------------------------------------------------
_client: Optional[httpx.AsyncClient] = None


async def startup_client() -> None:
    global _client
    if _client is not None:
        return
    cfg = get_config()
    timeout = httpx.Timeout(
        float(cfg.panel.get("timeout_seconds", 20)),
        connect=5.0,
    )
    limits = httpx.Limits(
        max_connections=100,
        max_keepalive_connections=50,
        keepalive_expiry=60.0,
    )
    _client = httpx.AsyncClient(
        verify=bool(cfg.panel.get("verify_ssl", True)),
        timeout=timeout,
        limits=limits,
        follow_redirects=True,
        http2=False,  # Pasarguard / nginx upstreams aren't always h2
    )
    log.info("HTTP client pool initialised (keepalive=50)")


async def shutdown_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _prepare_request_headers(req: Request) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in req.headers.items():
        if k.lower() in _STRIP_REQUEST_HEADERS:
            continue
        out[k] = v
    return out


# ----------------------------------------------------------------------
# Main forward
# ----------------------------------------------------------------------
async def forward_subscription(request: Request, path: str) -> Response:
    cfg = get_config()
    cache = get_cache()

    if ".." in path or path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid path")

    upstream_url = f"{cfg.panel_base_url}/{path}"
    if request.url.query:
        upstream_url = f"{upstream_url}?{request.url.query}"

    headers = _prepare_request_headers(request)

    # Skip body read for safe methods — saves a roundtrip and avoids
    # buffering useless data.
    body = b""
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        body = await request.body()

    if _client is None:  # safety net (shouldn't happen)
        await startup_client()
    assert _client is not None

    log.info("→ %s %s", request.method, upstream_url)

    try:
        r = await _client.request(
            request.method, upstream_url, headers=headers, content=body,
        )
    except httpx.TimeoutException:
        log.warning("Upstream timeout: %s", upstream_url)
        raise HTTPException(status_code=504, detail="Upstream timeout")
    except httpx.RequestError as e:
        log.error("Upstream error: %s", e)
        raise HTTPException(status_code=502, detail="Upstream error")

    out_body = r.content
    content_type = r.headers.get("content-type", "")

    if r.status_code == 200 and out_body:
        try:
            out_body = modify_body(out_body, content_type, cache)
        except Exception as exc:
            log.exception("Body modification failed: %s", exc)

    final_headers = build_response_headers(dict(r.headers), cache)

    log.info("← %s %s (%d bytes)", r.status_code, upstream_url, len(out_body))

    return Response(
        content=out_body,
        status_code=r.status_code,
        headers=final_headers,
        media_type=final_headers.get("content-type"),
    )
