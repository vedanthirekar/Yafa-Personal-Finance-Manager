"""FastAPI application factory and lifespan."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from .core.config import get_settings
from .core.logging import configure_logging, configure_telemetry, get_logger
from .routers import auth, categorize, forecast, powerbi, transactions, voice, ws

settings = get_settings()
configure_logging(settings)
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Load models before serving traffic.

    The embedding model (~80MB) and Whisper weights take seconds to load. Doing
    it here means the cost is paid at boot -- where the container healthcheck's
    start_period absorbs it -- instead of being charged to whichever user
    happens to send the first request.
    """
    from .services import categorizer, speech

    log.info("startup.begin", environment=settings.environment)

    try:
        await categorizer.warm_up()
        log.info("startup.categorizer_ready", model=settings.embedding_model_name)
    except Exception as exc:
        # A cold categorizer degrades to "Uncategorized" rather than 500s, so
        # this is worth logging loudly but not worth refusing to boot over.
        log.error("startup.categorizer_failed", error=str(exc), exc_info=True)

    try:
        speech.warm_up()
        log.info("startup.whisper_ready", model=settings.whisper_model_size)
    except Exception as exc:
        log.error("startup.whisper_failed", error=str(exc), exc_info=True)

    log.info("startup.complete")
    yield

    await categorizer.shutdown()
    log.info("shutdown.complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="YAFA API",
        description=(
            "AI-powered expense tracker. Voice capture via Whisper, semantic "
            "categorization via BERT embeddings + Qdrant vector search, and "
            "time-series spend forecasting."
        ),
        version="2.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
    configure_telemetry(app, settings)

    app.include_router(auth.router)
    app.include_router(transactions.router)
    app.include_router(voice.router)
    app.include_router(categorize.router)
    app.include_router(forecast.router)
    app.include_router(powerbi.router)
    app.include_router(ws.router)

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        """Liveness only -- deliberately does not touch Postgres or Qdrant.

        The container healthcheck polls this, and a check that fails when a
        dependency blips would restart a process that was working fine.
        Dependency status lives at /health/ready.
        """
        return {"status": "ok", "version": app.version}

    @app.get("/health/ready", tags=["ops"])
    async def readiness() -> JSONResponse:
        """Readiness -- reports on each backing service."""
        from sqlalchemy import text

        from .core.database import engine
        from .services import categorizer

        checks: dict[str, str] = {}

        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {exc}"

        try:
            checks["qdrant"] = "ok" if await categorizer.ping() else "error: unreachable"
        except Exception as exc:
            checks["qdrant"] = f"error: {exc}"

        healthy = all(v == "ok" for v in checks.values())
        return JSONResponse(
            content={"status": "ready" if healthy else "degraded", "checks": checks},
            status_code=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Log the traceback, return an opaque body.

        Exception text can carry connection strings and query fragments, so it
        goes to the log and never to the client.
        """
        log.error(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            error=str(exc),
            exc_info=True,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

    return app


app = create_app()
