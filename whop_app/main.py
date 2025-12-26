"""
Whop Embedded App - Main Entry Point

A FastAPI application that serves as an embedded app within Whop platform.
Handles user authentication, subscription checks, and webhook events.

Usage:
    Development:
        uvicorn main:app --reload --port 8000

    Production:
        gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000

Environment Variables:
    Required:
        - WHOP_API_KEY: Your Whop API key
        - WEBHOOK_SECRET: Secret for validating webhooks

    Optional:
        - DATABASE_URL: Database connection string
        - DEV_MODE: Enable development mode (default: false)
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from core.database import close_db, init_db, is_database_configured
from routes.dashboard import router as dashboard_router
from routes.webhook_whop import router as webhook_router

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.DEV_MODE else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Handles startup and shutdown events:
    - Startup: Initialize database, log configuration
    - Shutdown: Close database connections
    """
    # Startup
    logger.info(f"Starting {settings.APP_NAME}")
    logger.info(f"DEV_MODE: {settings.DEV_MODE}")

    if is_database_configured():
        logger.info("Initializing database...")
        await init_db()
    else:
        logger.info("Running without database (DATABASE_URL not set)")

    yield

    # Shutdown
    logger.info("Shutting down...")
    await close_db()


# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    description="Embedded application for Whop platform",
    version="1.0.0",
    lifespan=lifespan,
    # Disable docs in production for security
    docs_url="/docs" if settings.DEV_MODE else None,
    redoc_url="/redoc" if settings.DEV_MODE else None,
)

# CORS configuration
# Whop embeds apps in iframe, so CORS should allow Whop domain
app.add_middleware(
    CORSMiddleware,
    # In production, restrict to Whop domains
    allow_origins=[
        "https://whop.com",
        "https://*.whop.com",
    ]
    if not settings.DEV_MODE
    else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
# Dashboard: Main app UI loaded in Whop iframe
app.include_router(dashboard_router)

# Webhooks: Receive events from Whop
app.include_router(webhook_router)


@app.get("/")
async def root():
    """
    Root endpoint.

    Simple health check / info endpoint.
    In production embedded apps, users access /dashboard instead.
    """
    return {
        "app": settings.APP_NAME,
        "status": "running",
        "docs": "/docs" if settings.DEV_MODE else "disabled",
    }


@app.get("/health")
async def health_check():
    """
    Health check endpoint.

    Used by load balancers and monitoring systems.
    """
    return {
        "status": "healthy",
        "database": "connected" if is_database_configured() else "not configured",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.DEV_MODE,
    )
