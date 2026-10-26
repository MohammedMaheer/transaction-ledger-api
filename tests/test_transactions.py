from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from tests.helpers import account, balance, entry, history


async def test_credit_debit_and_balance_consistency(client):
    account_id = await account(client)
    for amount, kind, reference in [
        ("100.00", "credit", "1"),
        ("50.00", "credit", "2"),
        ("30.00", "debit", "3"),
        ("20.00", "debit", "4"),
    ]:
        response = await entry(client, account_id, amount, kind, reference, description="Example")
        assert response.status_code == 201, response.text
        assert response.json()["amount"] == amount
        assert response.json()["description"] == "Example"
        assert response.json()["account_id"] == account_id
    assert await balance(client, account_id) == Decimal("100.00")
    assert (await history(client, account_id))["pagination"]["total_records"] == 4


async def test_decimal_arithmetic_and_exact_balance_debit(client):
    account_id = await account(client)
    for i in range(10):
        assert (await entry(client, account_id, "0.10", reference=str(i))).status_code == 201
    assert await balance(client, account_id) == Decimal("1.00")
    assert (await entry(client, account_id, "1", "debit", "all")).json()["amount"] == "1.00"
    assert await balance(client, account_id) == Decimal("0.00")


async def test_insufficient_funds_leaves_no_changes(client):
    account_id = await account(client)
    await entry(client, account_id, "10.00")
    response = await entry(client, account_id, "10.01", "debit", "too-much")
    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "INSUFFICIENT_FUNDS",
            "message": "Account has insufficient balance",
            "details": {},
        }
    }
    assert await balance(client, account_id) == Decimal("10.00")
    assert (await history(client, account_id))["pagination"]["total_records"] == 1


@pytest.mark.parametrize(
    "amount",
    [
        "0",
        "0.00",
        "-0.01",
        "1.001",
        "1.000",
        "abc",
        "NaN",
        "Infinity",
        "1e2",
        "10000000000000000.00",
        " 1.00 ",
        "01.00",
        "1.",
        ".01",
        "",
        None,
        1.1,
        1,
        True,
        {},
        [],
    ],
)
async def test_invalid_amounts(client, amount):
    account_id = await account(client)
    response = await entry(client, account_id, amount)
    assert response.status_code == 422, response.text
    assert await balance(client, account_id) == Decimal("0.00")
    assert not (await history(client, account_id))["data"]


@pytest.mark.parametrize(
    "changes",
    [
        {"type": "CREDIT"},
        {"type": "refund"},
        {"type": None},
        {"type": 1},
        {"reference_id": " "},
        {"reference_id": None},
        {"reference_id": 123},
        {"reference_id": "x" * 101},
        {"description": None},
        {"description": 42},
        {"description": "x" * 2001},
        {"unexpected": "field"},
        {"reference_id": "a\x00b"},
        {"description": "a\x00b"},
    ],
)
async def test_strict_fields(client, changes):
    account_id = await account(client)
    payload = {"type": "credit", "amount": "10.00", "reference_id": "valid", **changes}
    response = await client.post(f"/api/v1/accounts/{account_id}/transactions", json=payload)
    assert response.status_code == 422


@pytest.mark.parametrize("missing", ["type", "amount", "reference_id"])
async def test_required_transaction_fields(client, missing):
    account_id = await account(client)
    payload = {"type": "credit", "amount": "10.00", "reference_id": "valid"}
    del payload[missing]
    assert (
        await client.post(f"/api/v1/accounts/{account_id}/transactions", json=payload)
    ).status_code == 422


async def test_missing_accounts_and_bad_uuid(client):
    assert (await entry(client, str(uuid4()))).status_code == 404
    assert (await entry(client, "bad-uuid")).status_code == 422
    assert (await client.get(f"/api/v1/accounts/{uuid4()}/transactions")).status_code == 404


async def test_duplicate_reference_and_cross_account_reuse(client):
    first, second = await account(client), await account(client)
    assert (await entry(client, first)).status_code == 201
    duplicate = await entry(client, first, "200.00")
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "DUPLICATE_REFERENCE"
    assert (await entry(client, second)).status_code == 201
    assert await balance(client, first) == Decimal("100.00")
    assert len((await history(client, first))["data"]) == 1


async def test_duplicate_debit_reported_before_funds_check(client):
    account_id = await account(client)
    await entry(client, account_id, "10.00")
    assert (await entry(client, account_id, "10.00", "debit", "withdraw")).status_code == 201
    assert (await entry(client, account_id, "10.00", "debit", "withdraw")).status_code == 409
    assert await balance(client, account_id) == Decimal("0.00")


async def test_balance_overflow_returns_business_error_and_rolls_back(client):
    account_id = await account(client)
    assert (await entry(client, account_id, "9999999999999999.99")).status_code == 201
    response = await entry(client, account_id, "0.01", reference="overflow")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BALANCE_LIMIT_EXCEEDED"
    assert await balance(client, account_id) == Decimal("9999999999999999.99")
    assert len((await history(client, account_id))["data"]) == 1


async def test_filter_pagination_and_deterministic_sort(client, engine):
    account_id = await account(client)
    other = await account(client)
    for i, kind in enumerate(["credit", "credit", "debit", "credit", "debit"]):
        assert (await entry(client, account_id, "10.00", kind, str(i))).status_code == 201
    await entry(client, other)
    data = (await history(client, account_id))["data"]
    assert data == sorted(
        data, key=lambda item: (item["created_at"], UUID(item["id"])), reverse=True
    )
    async with engine.begin() as connection:
        # Controlled fixture timestamps exercise the secondary ID ordering for ties.
        await connection.execute(
            text("UPDATE transactions SET created_at = '2026-01-01T00:00:00Z'")
        )
    credits = await history(client, account_id, type="credit", page=1, limit=2)
    assert credits["pagination"] == {
        "current_page": 1,
        "page_size": 2,
        "total_records": 3,
        "total_pages": 2,
    }
    assert all(item["type"] == "credit" for item in credits["data"])
    second = await history(client, account_id, type="credit", page=2, limit=2)
    combined = credits["data"] + second["data"]
    assert [item["id"] for item in combined] == sorted(
        [item["id"] for item in combined], reverse=True
    )
    assert len({item["id"] for item in combined}) == 3
    assert not (await history(client, account_id, page=100))["data"]
    empty = await history(client, await account(client))
    assert empty["pagination"]["total_pages"] == 0
    assert empty["pagination"]["page_size"] == 20


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"page": -1},
        {"page": "abc"},
        {"page": "1.1"},
        {"page": 1000001},
        {"limit": 0},
        {"limit": -1},
        {"limit": 101},
        {"limit": "abc"},
        {"type": "refund"},
        {"other": "x"},
    ],
)
async def test_history_query_validation(client, params):
    account_id = await account(client)
    response = await client.get(f"/api/v1/accounts/{account_id}/transactions", params=params)
    assert response.status_code == 422


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
async def test_transactions_immutable_through_api(client, method):
    account_id = await account(client)
    created = (await entry(client, account_id)).json()
    for suffix in ["", f"/{created['id']}"]:
        response = await client.request(
            method, f"/api/v1/accounts/{account_id}/transactions{suffix}", json={"amount": "1.00"}
        )
        assert response.status_code in (404, 405)
        assert "error" in response.json()
    assert (await history(client, account_id))["data"] == [created]
    assert await balance(client, account_id) == Decimal("100.00")
