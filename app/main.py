"""FastAPI application entry point."""

import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api import events_router
from app.config import get_settings
from app.metrics import (
    DLQ_LENGTH,
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_TOTAL,
    QUEUE_LENGTH,
)
from app.services import get_redis_client

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for startup/shutdown."""
    settings = get_settings()

    # Startup
    await logger.ainfo(
        "application_starting",
        app_name=settings.app_name,
        env=settings.app_env,
    )

    # Connect to Redis
    redis_client = get_redis_client()
    await redis_client.connect()

    yield

    # Shutdown
    await redis_client.disconnect()
    await logger.ainfo("application_shutdown")


def create_app() -> FastAPI:
    """Application factory for creating FastAPI instance."""
    settings = get_settings()

    app = FastAPI(
        title="Event Notification Service",
        description=(
            "An event-driven notification service with background worker processing. "
            "Demonstrates async architecture, reliability patterns, and clean API design."
        ),
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.app_env == "development" else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Prometheus metrics middleware
    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next) -> Response:
        """Record request metrics for Prometheus."""
        # Skip metrics endpoint itself
        if request.url.path == "/metrics":
            return await call_next(request)

        start_time = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start_time

        # Record metrics
        endpoint = request.url.path
        HTTP_REQUESTS_TOTAL.labels(
            method=request.method,
            endpoint=endpoint,
            status_code=response.status_code,
        ).inc()

        HTTP_REQUEST_DURATION_SECONDS.labels(
            method=request.method,
            endpoint=endpoint,
        ).observe(duration)

        return response

    # Include routers
    app.include_router(events_router)

    # Prometheus metrics endpoint
    @app.get("/metrics", tags=["monitoring"], include_in_schema=False)
    async def prometheus_metrics() -> Response:
        """Prometheus metrics endpoint for scraping."""
        # Update queue metrics
        try:
            redis_client = get_redis_client()
            queue_len = await redis_client.get_queue_length()
            dlq_len = await redis_client.get_dlq_length()
            QUEUE_LENGTH.labels(queue_name="events:queue").set(queue_len)
            DLQ_LENGTH.set(dlq_len)
        except Exception:
            pass  # Don't fail metrics if Redis is down

        return Response(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST,
        )

    # Health check endpoint
    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        """Health check endpoint for load balancers and monitoring."""
        redis_client = get_redis_client()
        redis_healthy = await redis_client.health_check()

        return {
            "status": "healthy" if redis_healthy else "degraded",
            "redis": "connected" if redis_healthy else "disconnected",
        }

    # Queue stats endpoint
    @app.get("/stats", tags=["health"])
    async def queue_stats() -> dict[str, int]:
        """Get current queue statistics."""
        redis_client = get_redis_client()
        return {
            "queue_length": await redis_client.get_queue_length(),
            "dlq_length": await redis_client.get_dlq_length(),
        }

    return app


# Create app instance
app = create_app()
