"""FastAPI application entrypoint.

Run with:  uvicorn app.main:app --host 0.0.0.0 --port 8000
The SQLite schema is initialised automatically on startup.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import database
from .repository import Conflict, NotFound
from .routers import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-initialise (and optionally seed) the database at boot.
    database.init_db()
    yield


app = FastAPI(
    title="博物馆展柜照度预算 API",
    description=(
        "登记展柜与展品，提交带起止时间的照明区间，按时间线合并同展柜"
        "重叠灯光（重叠取最大照度），累计展品曝光量并报告首次超预算时间、"
        "超出量与每日剩余额度。"
    ),
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(router)


@app.exception_handler(NotFound)
def _not_found_handler(_request, exc: NotFound):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(Conflict)
def _conflict_handler(_request, exc: Conflict):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.get("/health", tags=["system"])
def health():
    """Liveness/readiness probe: verifies the database is reachable."""
    try:
        with database.connection() as conn:
            conn.execute("SELECT 1").fetchone()
        return {"status": "ok", "database": database.config.db_path()}
    except Exception as exc:  # pragma: no cover - defensive
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=503, content={"status": "error", "detail": str(exc)}
        )


@app.get("/", tags=["system"])
def root():
    return {
        "service": "museum-light-budget",
        "docs": "/docs",
        "health": "/health",
    }
