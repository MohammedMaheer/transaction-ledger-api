"""Integration tests use real committed PostgreSQL transactions on a disposable database."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from dotenv import dotenv_values
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.core.database import build_engine
from app.main import create_app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def database_url():
    url = os.environ.get("TEST_DATABASE_URL") or dotenv_values(ROOT / ".env").get(
        "TEST_DATABASE_URL"
    )
    if not url:
        pytest.fail("Set TEST_DATABASE_URL to a disposable PostgreSQL database ending in _test")
    parsed = make_url(url)
    if parsed.drivername != "postgresql+asyncpg" or not (parsed.database or "").endswith("_test"):
        pytest.fail("Tests require postgresql+asyncpg and a database name ending in _test")
    production_url = os.environ.get("DATABASE_URL") or dotenv_values(ROOT / ".env").get(
        "DATABASE_URL"
    )
    if production_url and make_url(production_url) == parsed:
        pytest.fail("TEST_DATABASE_URL must differ from DATABASE_URL")
    # Apply the actual Alembic revision, rather than using metadata.create_all.
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": url},
        check=True,
        capture_output=True,
        text=True,
    )
    return url


@pytest_asyncio.fixture(scope="session")
async def engine(database_url):
    engine = build_engine(database_url)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def clean_database(engine):
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE transactions, accounts"))
    yield
    # Every test additionally proves that stored balances match the persisted ledger.
    async with engine.connect() as connection:
        inconsistent = await connection.scalar(
            text("""
            SELECT count(*) FROM (
                SELECT a.id FROM accounts a
                LEFT JOIN transactions t ON t.account_id = a.id
                GROUP BY a.id, a.balance
                HAVING a.balance < 0 OR a.balance <> coalesce(sum(
                    CASE WHEN t.type = 'credit' THEN t.amount ELSE -t.amount END
                ), 0)
            ) AS inconsistent_accounts
        """)
        )
        assert inconsistent == 0, "Account balance diverged from successful ledger entries"


@pytest_asyncio.fixture
async def app(database_url):
    app = create_app(Settings(database_url=database_url, _env_file=None))
    async with app.router.lifespan_context(app):
        yield app


@pytest_asyncio.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        yield client
