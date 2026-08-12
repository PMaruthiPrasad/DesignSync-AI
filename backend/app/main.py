"""FastAPI application entrypoint.

In development the React app runs on the Vite dev server and talks to this API
across origins (hence CORS). In the Docker/Railway build the compiled frontend
is copied in and served from this same process, so one service serves both and
CORS becomes irrelevant.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import api_router
from app.config import BACKEND_DIR, get_settings
from app.database import init_db
from app.llm.factory import describe_active_provider

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("designsync")

# Where the Dockerfile places the compiled frontend.
FRONTEND_DIST = BACKEND_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_db()
    settings.upload_path.mkdir(parents=True, exist_ok=True)
    # Log the provider that will actually serve requests, not the one that was
    # requested — selecting an unconfigured provider falls back to the mock, and
    # that substitution should be visible in the logs rather than a surprise.
    provider_name, model = describe_active_provider(settings)
    logger.info(
        "DesignSync AI %s ready (requested=%s, active=%s, model=%s)",
        __version__,
        settings.llm_provider,
        provider_name,
        model,
    )
    yield


app = FastAPI(
    title="DesignSync AI",
    description="AI-powered software change impact analysis",
    version=__version__,
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Never leak an internal traceback to a client."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Check the server logs for details."},
    )


# --------------------------------------------------------------------------
# Single-page app (production build only)
# --------------------------------------------------------------------------

if FRONTEND_DIST.is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST / "assets"),
        name="assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str) -> FileResponse:
        """Serve built assets, falling back to index.html for client routes."""
        candidate = (FRONTEND_DIST / full_path).resolve()
        if full_path and _is_within(FRONTEND_DIST.resolve(), candidate) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")

    def _is_within(root: Path, candidate: Path) -> bool:
        try:
            candidate.relative_to(root)
            return True
        except ValueError:
            return False
