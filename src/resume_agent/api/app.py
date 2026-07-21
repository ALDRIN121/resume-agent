"""FastAPI app factory and production SPA serving."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .routers.library import router as library_router
from .routers.resume import router as resume_router
from .routers.resume import ws_router as resume_ws_router
from .routers.runs import router as runs_router
from .routers.settings import router as settings_router
from .routers.ws import router as ws_router
from .security import request_is_loopback

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    # Graceful shutdown: cancel any graph runs still in flight.
    from .run_manager import run_manager

    await run_manager.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(title="Resume Generator", version="2.0.1", lifespan=_lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _guard_mutations(request: Request, call_next):
        """Reject cross-site / non-loopback state-changing requests (no auth model)."""
        if request.method not in _SAFE_METHODS and not request_is_loopback(
            request.headers.get("host"), request.headers.get("origin")
        ):
            return JSONResponse(
                {"detail": "Forbidden: requests must originate from loopback."},
                status_code=403,
            )
        return await call_next(request)

    app.include_router(runs_router)
    app.include_router(library_router)
    app.include_router(resume_router)
    app.include_router(settings_router)
    app.include_router(ws_router)
    app.include_router(resume_ws_router)

    @app.get("/api/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    frontend_dist = _frontend_dist()
    if frontend_dist.exists():
        assets = frontend_dist / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        index_html = frontend_dist / "index.html"

        @app.get("/{path:path}", include_in_schema=False)
        async def spa_fallback(path: str) -> FileResponse:
            # Contain the join inside frontend_dist — never serve outside the bundle.
            candidate = (frontend_dist / path).resolve()
            if candidate.is_file() and candidate.is_relative_to(frontend_dist.resolve()):
                return FileResponse(candidate)
            return FileResponse(index_html)

    return app


def _frontend_dist() -> Path:
    return Path(__file__).resolve().parents[3] / "Frontend" / "dist"
