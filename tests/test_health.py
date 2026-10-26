import socket

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.main import create_app


async def test_health_reports_missing_schema(client, engine):
    async with engine.begin() as connection:
        await connection.execute(text("ALTER TABLE accounts RENAME TO accounts_health_test"))
    try:
        response = await client.get("/health")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "DATABASE_NOT_READY"
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("ALTER TABLE accounts_health_test RENAME TO accounts"))


async def test_unreachable_database_returns_sanitized_error(database_url):
    # Reserve a real local port without listening; PostgreSQL connections are refused.
    with socket.socket() as unused_port:
        unused_port.bind(("127.0.0.1", 0))
        port = unused_port.getsockname()[1]
        url = make_url(database_url).set(host="127.0.0.1", port=port)
        app = create_app(
            Settings(database_url=url.render_as_string(hide_password=False), _env_file=None)
        )
        async with (
            app.router.lifespan_context(app),
            AsyncClient(
                transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
            ) as client,
        ):
            for method, path, kwargs in [
                ("GET", "/health", {}),
                ("POST", "/api/v1/accounts", {"json": {"name": "Cannot connect"}}),
            ]:
                response = await client.request(method, path, **kwargs)
                assert response.status_code == 503
                assert response.json() == {
                    "error": {
                        "code": "DATABASE_UNAVAILABLE",
                        "message": "Database temporarily unavailable",
                        "details": {},
                    }
                }
                assert str(port) not in response.text
