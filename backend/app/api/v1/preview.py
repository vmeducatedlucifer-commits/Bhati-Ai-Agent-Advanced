"""Reverse proxy to servers the agent starts inside a sandbox."""

from __future__ import annotations

import hmac
import re
import time

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse

from app.api.deps import Auth
from app.core.config import settings
from app.core.logging import get_logger
from app.sandbox import sandboxes

log = get_logger("app.api.preview")
router = APIRouter(prefix="/preview", tags=["preview"])

PREVIEW_TICKET_TTL_S = 3600
PREVIEW_COOKIE_PREFIX = "bhati_pv_"


def preview_cookie_name(thread_id: str, port: int) -> str:
    safe_thread = "".join(c if c.isalnum() else "_" for c in thread_id)[:64]
    return f"{PREVIEW_COOKIE_PREFIX}{safe_thread}_{int(port)}"


def mint_preview_ticket(thread_id: str, port: int) -> str:
    """Short-lived signed ticket so the iframe (no auth headers) can load."""
    exp = int(time.time()) + PREVIEW_TICKET_TTL_S
    msg = f"{thread_id}:{int(port)}:{exp}".encode()
    sig = hmac.new(settings.SECRET_KEY.encode(), msg, "sha256").hexdigest()
    return f"{exp}.{sig}"


def check_preview_ticket(thread_id: str, port: int, ticket: str) -> bool:
    try:
        exp_str, sig = ticket.split(".", 1)
        if int(exp_str) < time.time():
            return False
        msg = f"{thread_id}:{int(port)}:{exp_str}".encode()
        expect = hmac.new(settings.SECRET_KEY.encode(), msg, "sha256").hexdigest()
        return hmac.compare_digest(expect, sig)
    except (ValueError, TypeError, AttributeError):
        return False


@router.get("/ticket")
async def preview_ticket(thread_id: str, port: int, _: Auth):
    return {
        "ticket": mint_preview_ticket(thread_id, port),
        "expires_in": PREVIEW_TICKET_TTL_S,
        "cookie_name": preview_cookie_name(thread_id, port),
    }

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-encoding", "content-length",
}

@router.api_route(
    "/{thread_id}/{port}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
)
async def proxy(thread_id: str, port: int, path: str, request: Request):
    # The iframe cannot send Authorization headers, so preview URLs carry a
    # short-lived HMAC ticket minted by an authenticated call. Open local
    # instances (no password) skip the check like every other route.
    # The ticket travels as ?ticket= on the first navigation; relative assets
    # (CSS/JS/img) reuse it via a per-preview cookie set by the frontend, so
    # every sub-resource must accept either.
    # Validate port bounds and block internal reserved ports (e.g. gateway 8081, internal services)
    if not (1 <= port <= 65535) or port in (8081,):
        return Response(
            content="Forbidden preview target.",
            status_code=403,
            media_type="text/plain",
        )

    ticket = request.query_params.get("ticket", "")
    if not ticket:
        ticket = request.cookies.get(preview_cookie_name(thread_id, port), "")
    if settings.auth_enabled:
        if not check_preview_ticket(thread_id, port, ticket):
            return Response(
                content="Preview link expired or invalid — reload it from the app.",
                status_code=403, media_type="text/plain",
            )
    box = await sandboxes.peek(thread_id)
    if box is None:
        base = f"http://127.0.0.1:{int(port)}"
    else:
        base = await box.endpoint(port)
        if not base:
            base = f"http://127.0.0.1:{int(port)}"

    url = f"{base}/{path}"
    # Forward the client's query upstream but never the preview ticket itself
    # (it is only for our gate — leaking it upstream needlessly widens scope).
    forward_params = [(k, v) for k, v in request.query_params.multi_items() if k != "ticket"]
    if forward_params:
        from urllib.parse import urlencode

        url += f"?{urlencode(forward_params, doseq=True)}"

    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in HOP_BY_HOP | {"host", "authorization", "cookie"}
    }
    body = await request.body()

    def loading_page(exc_str: str) -> Response:
        import html as _html
        safe_exc = _html.escape(exc_str)
        return Response(
            content=(
                f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
                f"<meta http-equiv='refresh' content='3'>"
                f"<style>body{{font-family:system-ui,sans-serif;padding:2rem;color:#71717a;text-align:center;background:#18181b}} "
                f"h3{{color:#e4e4e7;margin-bottom:0.5rem}} p{{font-size:14px;margin-bottom:1rem}} "
                f".spinner{{display:inline-block;width:24px;height:24px;border:3px solid rgba(255,255,255,0.1);border-top-color:#38bdf8;border-radius:50%;animation:spin 1s linear infinite}} "
                f"@keyframes spin{{to{{transform:rotate(360deg)}}}}</style></head><body>"
                f"<div class='spinner'></div>"
                f"<h3>Starting dev server on port {int(port)}...</h3>"
                f"<p>Waiting for the application to respond. Auto-reloading in 3 seconds...</p>"
                f"<pre style='font-size:11px;color:#a1a1aa;text-align:left;background:#27272a;padding:1rem;border-radius:8px;max-width:500px;margin:1rem auto;overflow:auto'>{safe_exc}</pre>"
                f"</body></html>"
            ),
            status_code=200,
            media_type="text/html",
        )

    try:
        client = httpx.AsyncClient(timeout=60, follow_redirects=False)
        upstream = await client.request(request.method, url, headers=headers, content=body)
    except Exception as exc:
        return loading_page(str(exc))

    response_headers = {
        k: v for k, v in upstream.headers.items() if k.lower() not in HOP_BY_HOP
    }
    # Let the preview render inside the app's iframe.
    response_headers.pop("x-frame-options", None)
    response_headers.pop("content-security-policy", None)

    content_type = upstream.headers.get("content-type", "")

    if "text/html" in content_type.lower():
        try:
            body_bytes = await upstream.aread()
            html_text = body_bytes.decode(errors="replace")
            # Inject base tag for relative assets using regex. When the
            # navigation carried ?ticket=, keep it in the base so links that
            # open without the cookie (new tab, copy-paste) still validate.
            # Same-origin sub-resources normally ride the preview cookie.
            import html as _html
            from urllib.parse import quote as _quote

            _base = f"/api/v1/preview/{thread_id}/{int(port)}/"
            _qt = request.query_params.get("ticket", "")
            if _qt and check_preview_ticket(thread_id, port, _qt):
                _base += f"?ticket={_quote(_qt, safe='')}"
            # NOTE: ticket is hex + dot only, but escape anyway if ever changed.
            base_tag = f'<base href="{_html.escape(_base, quote=True)}">'
            if re.search(r"<head[^>]*>", html_text, re.IGNORECASE):
                html_text = re.sub(r"(<head[^>]*>)", rf"\1{base_tag}", html_text, count=1, flags=re.IGNORECASE)
            else:
                html_text = base_tag + html_text

            response_headers["content-length"] = str(len(html_text.encode("utf-8")))
            await upstream.aclose()
            await client.aclose()
            return Response(
                content=html_text,
                status_code=upstream.status_code,
                headers=response_headers,
                media_type="text/html",
            )
        except Exception:
            pass # fallback to streaming if reading fails

    async def stream():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        stream(),
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=content_type,
    )
