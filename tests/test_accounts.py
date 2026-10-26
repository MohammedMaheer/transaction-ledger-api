from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest

from tests.helpers import account


async def test_create_account_zero_balance_and_system_fields(client):
    response = await client.post("/api/v1/accounts", json={"name": "  Jane Doe  "})
    assert response.status_code == 201
    body = response.json()
    assert UUID(body["id"]).version == 4
    assert body["name"] == "Jane Doe"
    assert body["balance"] == "0.00"
    assert datetime.fromisoformat(
        body["created_at"].replace("Z", "+00:00")
    ).utcoffset() == timedelta(0)
    other = await account(client)
    assert other != body["id"]
    balance = await client.get(f"/api/v1/accounts/{body['id']}/balance")
    assert balance.json() == {"account_id": body["id"], "balance": "0.00"}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": ""},
        {"name": " \n\t "},
        {"name": None},
        {"name": 123},
        {"name": "a\x00b"},
        {"name": "x" * 201},
        {"name": "Jane", "balance": "100.00"},
        {"name": "Jane", "balance": "0.00"},
        {"name": "Jane", "id": str(uuid4())},
        {"name": "Jane", "created_at": "2026-01-01T00:00:00Z"},
        {"name": "Jane", "unknown": True},
    ],
)
async def test_reject_invalid_account_and_client_owned_system_fields(client, payload):
    response = await client.post("/api/v1/accounts", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_missing_balance_and_invalid_uuid(client):
    response = await client.get(f"/api/v1/accounts/{uuid4()}/balance")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"
    response = await client.get("/api/v1/accounts/not-a-uuid/balance")
    assert response.status_code == 422


async def test_health_openapi_and_consistent_route_errors(client):
    assert (await client.get("/health")).json() == {"status": "ok", "database": "ok"}
    assert (await client.get("/docs")).status_code == 200
    schema = (await client.get("/openapi.json")).json()
    assert schema["paths"]["/api/v1/transfers"]["post"]["responses"]["201"]
    error_ref = schema["paths"]["/api/v1/accounts"]["post"]["responses"]["422"]
    assert error_ref["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorResponse")
    missing = await client.get("/unknown")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"


async def test_invalid_json_error_does_not_echo_input(client):
    response = await client.post(
        "/api/v1/accounts", content='{"secret":', headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert "secret" not in response.text
