from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import auth, files, health, purchases
from app.services.storage import StorageError, ensure_bucket


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Startup: idempotent bucket bootstrap. Logs and swallows errors so a
    # transient Supabase outage doesn't prevent the API from booting —
    # signed-URL endpoints will surface a 502 if the bucket is genuinely
    # unreachable when a request comes in.
    try:
        await ensure_bucket()
    except StorageError as exc:
        print(f"[startup] ensure_bucket failed (continuing): {exc}")

    yield

    # Shutdown: dispose engine cleanly to close pooled connections
    from app.db import engine
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Mintfolio API",
        description="Backend service for the Mintfolio precious metals portfolio platform.",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(auth.router, prefix="/auth")
    app.include_router(purchases.router)
    app.include_router(files.router)

    return app


app = create_app()
