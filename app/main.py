import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api import accounts, transactions, transfers
from app.core.config import Settings, get_settings
from app.core.database import build_engine
from app.core.exceptions import ERROR_RESPONSES, LedgerError, install_exception_handlers


class HealthRead(BaseModel):
    status: str
    database: str


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logging.basicConfig(level=settings.log_level)
        engine = build_engine(str(settings.database_url))
        app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(
        title="Transaction Ledger API",
        version="1.0.0",
        description=(
            "Atomic account credits, debits, and transfers. Monetary values are decimal strings."
        ),
        lifespan=lifespan,
        responses=ERROR_RESPONSES,
    )
    install_exception_handlers(app)
    api = APIRouter(prefix="/api/v1")
    api.include_router(accounts.router)
    api.include_router(transactions.router)
    api.include_router(transfers.router)
    app.include_router(api)

    @app.get(
        "/health",
        response_model=HealthRead,
        tags=["Operations"],
        summary="Check database readiness",
    )
    async def health():
        async with app.state.session_factory() as session:
            # Check both connectivity and the migrated schema without changing any data.
            ready = await session.scalar(
                text(
                    "SELECT to_regclass('public.accounts') IS NOT NULL "
                    "AND to_regclass('public.transactions') IS NOT NULL"
                )
            )
            if not ready:
                raise LedgerError(503, "DATABASE_NOT_READY", "Database migrations are required")
        return HealthRead(status="ok", database="ok")

    return app
