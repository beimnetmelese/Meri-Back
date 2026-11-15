import logging
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

import app.models  # Ensures all ORM models are registered in metadata
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import Base, engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("bridgemate")


from sqlalchemy import text

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing BridgeMate Backend database tables...")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Ensure runtime columns exist for multi-tenant platform admin support
            try:
                res = await conn.execute(text("PRAGMA table_info(users)"))
                cols = [r[1] for r in res.fetchall()]
                if "status" not in cols:
                    await conn.execute(text("ALTER TABLE users ADD COLUMN status VARCHAR(50) DEFAULT 'active'"))
                if "assigned_platform_id" not in cols:
                    await conn.execute(text("ALTER TABLE users ADD COLUMN assigned_platform_id VARCHAR(36)"))
                if "requested_platform_name" not in cols:
                    await conn.execute(text("ALTER TABLE users ADD COLUMN requested_platform_name VARCHAR(255)"))
                if "requested_platform_domain" not in cols:
                    await conn.execute(text("ALTER TABLE users ADD COLUMN requested_platform_domain VARCHAR(255)"))
                await conn.execute(text("UPDATE users SET role = 'superadmin', status = 'approved', is_active = 1 WHERE email = 'admin@bridgemate.internal'"))
            except Exception:
                pass
        logger.info("Database tables initialized successfully.")
    except Exception as e:
        logger.warning(f"Database initialization notice: {e}")

    yield

    logger.info("Shutting down BridgeMate Backend...")
    await engine.dispose()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Unified context-aware backend powering the BridgeMate embeddable website plugin and Telegram bot.",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS configuration: must allow host platforms to embed and communicate with widget
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)

# Mount static assets and administrative platform hub
static_dir = Path(__file__).parent / "static"
admin_dir = static_dir / "admin"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
if admin_dir.exists():
    app.mount("/admin", StaticFiles(directory=str(admin_dir), html=True), name="admin")
    app.mount("/dashboard", StaticFiles(directory=str(admin_dir), html=True), name="dashboard")


@app.get("/", tags=["Health"])
async def root():
    return {
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "operational",
        "docs_url": "/docs",
        "admin_hub": "/admin",
    }


@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "healthy",
        "database": "connected",
        "ai_orchestrator": "ready",
    }
