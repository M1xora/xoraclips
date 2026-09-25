import os

# Before anything imports yt-dlp (youtube_source does): see compat.py.
try:
    from backend import compat  # noqa: F401
except ImportError:
    import compat  # noqa: F401

from dotenv import load_dotenv

# Automatically load environment variables from backend/.env or root .env
_base_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_base_dir, ".env"))
load_dotenv(os.path.join(_base_dir, "..", ".env"))
load_dotenv()

import logging
from contextlib import asynccontextmanager
from typing import List
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

try:
    from backend.secrets_guard import GEMINI_KEY_HEADER, install_log_redaction, is_mock_mode
except ImportError:
    from secrets_guard import GEMINI_KEY_HEADER, install_log_redaction, is_mock_mode

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("xoraclips")
# Scrub API keys from every log line (issue #8). Installed again at startup,
# after uvicorn has set up its own handlers.
install_log_redaction()


@asynccontextmanager
async def _lifespan(_app):
    # uvicorn has configured its log handlers by now; make sure they scrub keys too.
    install_log_redaction()
    if is_mock_mode():
        logger.warning("MOCK_MODE is on: analysis returns sample data and never calls Gemini or YouTube.")
    yield


app = FastAPI(
    title="XORACLIPS API",
    description="AI Powered YouTube Auto Clipper",
    lifespan=_lifespan,
)

# CORS (issue #45): only the app itself may read API responses. The frontend
# calls the API through the Vite proxy (same origin), so a browser tab on any
# other site gets no Access-Control-Allow-Origin header. Set ALLOWED_ORIGINS
# in .env (comma-separated) when the app is served from another address.
DEFAULT_ALLOWED_ORIGINS = "http://localhost:5174,http://127.0.0.1:5174"


def allowed_origins() -> List[str]:
    raw = os.environ.get("ALLOWED_ORIGINS", "").strip() or DEFAULT_ALLOWED_ORIGINS
    # A browser's Origin never ends in "/", so "https://site/" would never match.
    origins = (origin.strip().rstrip("/") for origin in raw.split(","))
    return [origin for origin in origins if origin]


CORS_ORIGINS = allowed_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", GEMINI_KEY_HEADER],
)


@app.middleware("http")
async def refuse_writes_from_other_sites(request: Request, call_next):
    """
    CORS only stops other sites from READING responses; a page can still send
    a POST without asking first (issue #45). A browser always sends Origin on
    such a request, so anything that changes state is refused unless it comes
    from an allowed origin. Requests without Origin (curl, scripts) pass; the
    Vite proxy forwards the app's own Origin, which is allowed.
    """
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin is not None and origin.rstrip("/") not in CORS_ORIGINS:
            return JSONResponse(status_code=403, content={"detail": "Origin not allowed"})
    return await call_next(request)


# The endpoints are grouped in routes_* modules (#60); main.py builds the app.
try:
    from backend import (
        routes_analyze, routes_cookies, routes_downloads, routes_media, routes_render, routes_system,
        routes_uploads,
    )
except ImportError:
    import routes_analyze
    import routes_cookies
    import routes_downloads
    import routes_media
    import routes_render
    import routes_system
    import routes_uploads

for _routes in (routes_system, routes_analyze, routes_render, routes_uploads, routes_cookies,
                routes_media, routes_downloads):
    app.include_router(_routes.router)

# Upload size limits, checked before the body is read (#58).
app.middleware("http")(routes_uploads.refuse_oversized_uploads)
