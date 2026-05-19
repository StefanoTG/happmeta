"""
Subscription content + header modifier.

Responsibilities:
  * Apply custom metadata headers (overriding any of the same name from panel).
  * Remove headers that the operator explicitly disabled.
  * Rename / decorate node names inside the subscription body. The body can
    be base64 (V2Ray-style), Clash/Mihomo YAML, sing-box JSON, or a list of
    raw URI links. We auto-detect, modify, then re-encode.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from typing import Any, Dict, List, Tuple
from urllib.parse import quote, unquote, urlparse, urlunparse

import yaml

from .database import Database


# These are the headers we manage. Anything not in this set is passed
# through untouched.
KNOWN_METADATA_HEADERS = {
    "profile-title",
    "profile-web-page-url",
    "profile-update-interval",
    "support-url",
    "subscription-userinfo",
    "content-disposition",
    "announce",
    "announce-url",
    "test-url",
}

# Headers we always strip from the upstream response (hop-by-hop or
# rewritten by FastAPI/uvicorn).
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "transfer-encoding",
    "upgrade",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "content-encoding",  # httpx already decoded
    "content-length",    # length changes after we modify body
}


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------
def build_response_headers(upstream_headers: Dict[str, str], db: Database) -> Dict[str, str]:
    """
    Merge upstream headers with operator-defined metadata.

    Logic:
      1. Start from upstream headers (lowercased keys).
      2. For every metadata row in DB:
         - enabled=1  -> override / inject
         - enabled=0  -> remove from output (even if upstream sent it)
    """
    lowered: Dict[str, str] = {}
    for k, v in upstream_headers.items():
        kl = k.lower()
        if kl in HOP_BY_HOP:
            continue
        lowered[kl] = v

    for row in db.list_metadata(include_disabled=True):
        name = row["name"].lower()
        if row["enabled"]:
            lowered[name] = row["value"]
        else:
            lowered.pop(name, None)

    return lowered


# ---------------------------------------------------------------------------
# Node renaming
# ---------------------------------------------------------------------------
def _apply_rules_to_name(name: str, rules: List[Dict[str, Any]]) -> str:
    out = name
    for r in rules:
        if not r["enabled"]:
            continue
        rt = r["rule_type"]
        rep = r["replacement"] or ""
        pat = r["pattern"] or ""
        try:
            if rt == "prefix":
                out = f"{rep}{out}"
            elif rt == "suffix":
                out = f"{out}{rep}"
            elif rt == "emoji":
                # Inject emoji at start if not already present.
                if rep and not out.startswith(rep):
                    out = f"{rep} {out}"
            elif rt == "regex" and pat:
                out = re.sub(pat, rep, out)
            elif rt == "template" and pat:
                # pattern acts as a python str.format template using {name}
                out = pat.replace("{name}", out).replace("{rep}", rep)
        except re.error:
            continue
    return out


# ---------- URI-style links (vmess/vless/trojan/ss) ----------
def _rename_uri_link(link: str, rules: List[Dict[str, Any]]) -> str:
    link = link.strip()
    if not link:
        return link
    try:
        if link.startswith("vmess://"):
            payload = link[len("vmess://"):]
            try:
                decoded = base64.b64decode(payload + "==").decode("utf-8", "ignore")
                obj = json.loads(decoded)
                if isinstance(obj, dict) and "ps" in obj:
                    obj["ps"] = _apply_rules_to_name(str(obj["ps"]), rules)
                    new_payload = base64.b64encode(
                        json.dumps(obj, ensure_ascii=False).encode("utf-8")
                    ).decode("ascii")
                    return f"vmess://{new_payload}"
            except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError):
                return link
            return link

        # vless / trojan / ss / hysteria etc. use #fragment as label
        if "#" in link:
            base, frag = link.split("#", 1)
            new_frag = _apply_rules_to_name(unquote(frag), rules)
            return f"{base}#{quote(new_frag, safe='')}"
    except Exception:
        return link
    return link


# ---------- Clash / Mihomo YAML ----------
def _rename_clash(text: str, rules: List[Dict[str, Any]]) -> str:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return text
    if not isinstance(data, dict):
        return text

    proxies = data.get("proxies")
    if isinstance(proxies, list):
        rename_map: Dict[str, str] = {}
        for p in proxies:
            if isinstance(p, dict) and "name" in p:
                old = str(p["name"])
                new = _apply_rules_to_name(old, rules)
                if new != old:
                    rename_map[old] = new
                    p["name"] = new
        # Update references inside proxy-groups
        for grp in data.get("proxy-groups", []) or []:
            if isinstance(grp, dict) and isinstance(grp.get("proxies"), list):
                grp["proxies"] = [rename_map.get(x, x) for x in grp["proxies"]]
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


# ---------- sing-box JSON ----------
def _rename_singbox(text: str, rules: List[Dict[str, Any]]) -> str:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(data, dict) and isinstance(data.get("outbounds"), list):
        for ob in data["outbounds"]:
            if isinstance(ob, dict) and "tag" in ob:
                ob["tag"] = _apply_rules_to_name(str(ob["tag"]), rules)
    return json.dumps(data, ensure_ascii=False, indent=2)


# ---------- base64 list ----------
_B64_RE = re.compile(r"^[A-Za-z0-9+/=\s]+$")


def _try_decode_base64(text: str) -> Tuple[bool, str]:
    candidate = text.strip()
    if not candidate or len(candidate) < 16 or not _B64_RE.match(candidate):
        return False, text
    try:
        padded = candidate + "=" * (-len(candidate) % 4)
        decoded = base64.b64decode(padded).decode("utf-8", "ignore")
    except (binascii.Error, UnicodeDecodeError):
        return False, text
    # Heuristic: must contain at least one known proxy scheme
    if any(s in decoded for s in ("vmess://", "vless://", "trojan://", "ss://", "hysteria")):
        return True, decoded
    return False, text


def _detect_format(body: str, content_type: str) -> str:
    ct = (content_type or "").lower()
    stripped = body.lstrip()

    if "yaml" in ct or stripped.startswith("proxies:") or "\nproxies:" in body[:2048]:
        return "clash"
    if "json" in ct or stripped.startswith("{"):
        # sing-box configs always contain "outbounds"
        if '"outbounds"' in body[:4096]:
            return "singbox"
        return "json"
    is_b64, _ = _try_decode_base64(body)
    if is_b64:
        return "base64"
    if any(s in body[:4096] for s in ("vmess://", "vless://", "trojan://", "ss://")):
        return "plain"
    return "unknown"


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------
def modify_body(body: bytes, content_type: str, db: Database) -> bytes:
    """Apply node-rename rules to a subscription body. Preserves encoding."""
    rules = db.list_node_rules(only_enabled=True)
    if not rules:
        return body

    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return body  # binary — leave alone

    fmt = _detect_format(text, content_type)

    if fmt == "clash":
        new_text = _rename_clash(text, rules)
    elif fmt == "singbox":
        new_text = _rename_singbox(text, rules)
    elif fmt == "base64":
        ok, decoded = _try_decode_base64(text)
        if not ok:
            return body
        lines = [_rename_uri_link(line, rules) for line in decoded.splitlines()]
        rebuilt = "\n".join(lines).strip() + "\n"
        new_text = base64.b64encode(rebuilt.encode("utf-8")).decode("ascii")
    elif fmt == "plain":
        lines = [_rename_uri_link(line, rules) for line in text.splitlines()]
        new_text = "\n".join(lines)
    else:
        return body

    return new_text.encode("utf-8")
