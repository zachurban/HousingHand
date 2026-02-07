"""FastAPI application for the HousingHand pipeline intelligence platform.

This module creates the FastAPI ``app`` instance, configures CORS
middleware, registers all API routers under the ``/api/v1`` prefix, and
defines the application lifespan (startup / shutdown hooks).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncIterator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config.settings import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan context manager.

    * **Startup**: validates database connectivity, logs configuration
      summary, and warms any cached resources.
    * **Shutdown**: performs graceful cleanup.
    """
    settings = get_settings()
    logger.info(
        "HousingHand API starting (debug=%s, host=%s, port=%d)",
        settings.api_debug,
        settings.api_host,
        settings.api_port,
    )

    # Verify database is reachable.
    try:
        from src.database.connection import get_engine
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        logger.info("Database connection verified")
    except Exception:
        logger.warning(
            "Database connection could not be verified at startup -- "
            "requests that require the database will fail until connectivity is restored"
        )

    yield  # Application runs here.

    logger.info("HousingHand API shutting down")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    """Build and return a fully configured FastAPI application instance."""
    settings = get_settings()

    app = FastAPI(
        title="HousingHand",
        description=(
            "Development Pipeline Intelligence Platform for the HousingMind "
            "ecosystem.  Tracks affordable housing projects from concept "
            "through certificate of occupancy, identifies systemic "
            "bottlenecks, predicts timelines, and measures the impact of "
            "policy reforms."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # -- CORS ---------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -- Global exception handler -------------------------------------------
    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

    # -- Routers ------------------------------------------------------------
    from src.api.endpoints.analytics import router as analytics_router
    from src.api.endpoints.health import router as health_router
    from src.api.endpoints.portfolio import router as portfolio_router
    from src.api.endpoints.predictions import router as predictions_router
    from src.api.endpoints.projects import router as projects_router
    from src.api.endpoints.reforms import router as reforms_router
    from src.api.webhooks import router as webhooks_router

    api_prefix = "/api/v1"

    app.include_router(projects_router, prefix=api_prefix)
    app.include_router(analytics_router, prefix=api_prefix)
    app.include_router(portfolio_router, prefix=api_prefix)
    app.include_router(predictions_router, prefix=api_prefix)
    app.include_router(health_router, prefix=api_prefix)
    app.include_router(reforms_router, prefix=api_prefix)
    app.include_router(webhooks_router, prefix=api_prefix)

    # -- Root / health-check ------------------------------------------------
    @app.get("/", include_in_schema=False)
    async def root() -> dict:
        """Root endpoint -- basic service liveness check."""
        return {
            "service": "HousingHand",
            "version": "0.1.0",
            "status": "ok",
            "timestamp": datetime.utcnow().isoformat(),
        }

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict:
        """Kubernetes / load-balancer health-check endpoint."""
        return {"status": "healthy"}

    return app


# The canonical application object used by ``uvicorn src.api.app:app``.
app = create_app()
