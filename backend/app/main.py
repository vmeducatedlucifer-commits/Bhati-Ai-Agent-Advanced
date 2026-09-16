import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app import __version__
from app.agent.scheduler import start as start_scheduler
from app.agent.scheduler import stop as stop_scheduler
from app.api.v1 import api_router
from app.browser import browsers
from app.core.config import REPO_DIR, settings
from app.core.errors import install_error_handlers
from app.core.logging import setup_logging
from app.db.mongo import mongo_manager
from app.db.session import init_db
from app.sandbox.manager import sandboxes
from app.storage import gdrive_manager
from app.telegram import telegram_bot

setup_logging()
log = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import secrets
    log.info("Starting Rawal AI v%s", __version__)
    if settings.ENV == "prod":
        if settings.SECRET_KEY.startswith("dev-secret-") or len(settings.SECRET_KEY) < 32:
            log.warning("Generating ephemeral production SECRET_KEY for this boot session.")
            settings.SECRET_KEY = secrets.token_urlsafe(48)

        if settings.JWT_SECRET.startswith("dev-jwt-secret-") or len(settings.JWT_SECRET) < 32:
            log.warning("Generating ephemeral production JWT_SECRET for this boot session.")
            settings.JWT_SECRET = secrets.token_urlsafe(48)

        if not settings.GATEWAY_SHARED_SECRET or settings.GATEWAY_SHARED_SECRET.startswith("dev-"):
            log.warning("Generating ephemeral production GATEWAY_SHARED_SECRET for this boot session.")
            settings.GATEWAY_SHARED_SECRET = secrets.token_urlsafe(48)

        if not settings.AUTH_PASSWORD and not settings.ALLOW_ANONYMOUS:
            log.info("Running in open anonymous mode on Render. Set AUTH_PASSWORD to enable login gate.")
            settings.ALLOW_ANONYMOUS = True
    settings.ensure_dirs()
    await init_db()
    await gdrive_manager.init()
    await telegram_bot.init()
    sandboxes.start_reaper()
    start_scheduler()
    yield
    log.info("Shutting down")
    await stop_scheduler()
    await telegram_bot.shutdown()
    await browsers.close_all()
    await sandboxes.shutdown()
    await mongo_manager.shutdown()


_is_prod = settings.ENV == "prod"

app = FastAPI(
    title=settings.APP_NAME,
    version=__version__,
    lifespan=lifespan,
    # Closed-source: never publish the route schema in prod. Dev keeps docs.
    docs_url=None if _is_prod else "/api/docs",
    redoc_url=None if _is_prod else "/api/redoc",
    openapi_url=None if _is_prod else "/api/openapi.json",
)


class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Minimal hardening headers on every response.

    - nosniff: blocks MIME-sniffing driven XSS.
    - SAMEORIGIN: no clickjacking from evil sites; our own preview iframe
      is same-origin so it keeps working (preview strips upstream framing).
    - no-referrer: internal thread/URL ids never leak via Referer.
    - Permissions-Policy: no camera/mic/location for any rendered page.
    """

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(self), geolocation=()"
        # HTTPS is terminated at the edge (Render/Cloudflare); pin it so a
        # future downgrade can never silently stick.
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if request.url.path == "/api" or request.url.path.startswith("/api/"):
            # Authenticated data must never sit in disk/memory caches, the
            # service worker, or shared proxies — every read revalidates live.
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response


app.add_middleware(_SecurityHeadersMiddleware)

cors_wildcard = settings.CORS_ORIGINS in ("*", "")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if cors_wildcard else settings.cors_origins,
    # Browsers reject wildcard origins with credentials; only send
    # credentials to explicitly listed origins.
    allow_credentials=not cors_wildcard,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

install_error_handlers(app)

app.include_router(api_router, prefix="/api/v1")

# Mount frontend
frontend_dist = REPO_DIR / "frontend" / "dist"

if frontend_dist.is_dir():
    # Mount assets folder
    assets_dir = frontend_dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    # Hand off any unhandled paths to the frontend SPA — but never for
    # /api/*: unknown API routes must stay machine-readable JSON 404s (and
    # must not serve the SPA, which confuses scanners and hides mistakes).
    @app.api_route("/{full_path:path}", methods=["GET"])
    async def serve_frontend(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": "Not found"}},
            )
        path = frontend_dist / full_path
        if path.is_file():
            return FileResponse(path)
        # The app shell must never be served stale: a cached index.html would
        # keep running yesterday's code (and yesterday's bugs) after deploys.
        return FileResponse(
            frontend_dist / "index.html",
            headers={"Cache-Control": "no-cache, must-revalidate"},
        )
else:
    log.warning(f"Frontend dist not found at {frontend_dist}. Running API only.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
