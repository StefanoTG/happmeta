"""
HTTP proxy logic. Forwards subscription requests to the real Pasarguard
panel, then rewrites headers + body before returning to the client.
"""
from __future__ import annotations

import logging
from typing import Tuple

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import Response

from .config import get_config
from .database import get_db
from .modifier import build_response_headers, modify_body

log = logging.getLogger("subproxy")


# Headers we don't want to leak from the client to the upstream panel
# (Host is rewritten explicitly).
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
    # We strip accept-encoding so the upstream always returns identity
    # (uncompressed). Otherwise the upstream may answer with brotli/zstd,
    # which httpx does not decode by default, and we would forward raw
    # compressed bytes after dropping the content-encoding header.
    "accept-encoding",
}


def _prepare_request_headers(req: Request) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in req.headers.items():
        if k.lower() in _STRIP_REQUEST_HEADERS:
            continue
        out[k] = v
    return out


async def forward_subscription(request: Request, path: str) -> Response:
    """
    Forward a subscription request to the upstream panel, then rewrite
    metadata headers and body (node names).
    """
    cfg = get_config()
    db = get_db()

    if ".." in path or path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid path")

    upstream_url = f"{cfg.panel_base_url}/{path}"
    if request.url.query:
        upstream_url = f"{upstream_url}?{request.url.query}"

    headers = _prepare_request_headers(request)
    verify = bool(cfg.panel.get("verify_ssl", True))
    timeout = float(cfg.panel.get("timeout_seconds", 20))

    log.info("→ Forwarding %s %s", request.method, upstream_url)

    try:
        async with httpx.AsyncClient(
            verify=verify, timeout=timeout, follow_redirects=True
        ) as client:
            r = await client.request(
                request.method, upstream_url, headers=headers,
                content=await request.body(),
            )
    except httpx.TimeoutException:
        log.warning("Upstream timeout: %s", upstream_url)
        raise HTTPException(status_code=504, detail="Upstream timeout")
    except httpx.RequestError as e:
        log.error("Upstream error: %s", e)
        raise HTTPException(status_code=502, detail="Upstream error")

    body = r.content
    content_type = r.headers.get("content-type", "")

    # Mutate body (node renames) — only if it's a subscription-ish response
    if r.status_code == 200 and body:
        try:
            body = modify_body(body, content_type, db)
        except Exception as exc:  # never break the proxy because of modifier bugs
            log.exception("Body modification failed: %s", exc)

    # Merge / override headers
    final_headers = build_response_headers(dict(r.headers), db)

    log.info("← %s %s (%d bytes)", r.status_code, upstream_url, len(body))

    return Response(
        content=body,
        status_code=r.status_code,
        headers=final_headers,
        media_type=final_headers.get("content-type"),
    )
