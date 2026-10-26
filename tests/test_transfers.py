from decimal import Decimal
from uuid import uuid4

import pytest

from tests.helpers import account, balance, entry, history, transfer_payload


async def test_successful_transfer_and_duplicate_retry(client):
    source, destination = await account(client), await account(client)
    await entry(client, source)
    await entry(client, destination, "50.00")
    payload = transfer_payload(source, destination, description="Rent")
    response = await client.post("/api/v1/transfers", json=payload)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["source_transaction"]["type"] == "debit"
    assert result["destination_transaction"]["type"] == "credit"
    assert result["source_transaction"]["account_id"] == source
    assert result["destination_transaction"]["account_id"] == destination
    assert (
        result["source_transaction"]["reference_id"]
        == result["destination_transaction"]["reference_id"]
        == "TRF-001"
    )
    assert result["source_transaction"]["amount"] == "30.00"
    assert result["source_transaction"]["description"] == "Rent"
    assert await balance(client, source) == Decimal("70.00")
    assert await balance(client, destination) == Decimal("80.00")
    assert (await client.post("/api/v1/transfers", json=payload)).status_code == 409
    changed = {**payload, "amount": "1.00"}
    assert (await client.post("/api/v1/transfers", json=changed)).status_code == 409
    assert await balance(client, source) == Decimal("70.00")
    assert len((await history(client, source))["data"]) == 2
    assert len((await history(client, destination))["data"]) == 2


async def test_insufficient_transfer_and_retry_after_funding(client):
    source, destination = await account(client), await account(client)
    payload = transfer_payload(source, destination)
    response = await client.post("/api/v1/transfers", json=payload)
    assert response.status_code == 400
    assert not (await history(client, source))["data"]
    assert not (await history(client, destination))["data"]
    await entry(client, source)
    assert (await client.post("/api/v1/transfers", json=payload)).status_code == 201


@pytest.mark.parametrize("missing_side", ["source", "destination", "both"])
async def test_missing_transfer_account_rolls_back(client, missing_side):
    existing = await account(client)
    await entry(client, existing)
    source = existing if missing_side == "destination" else str(uuid4())
    destination = existing if missing_side == "source" else str(uuid4())
    response = await client.post("/api/v1/transfers", json=transfer_payload(source, destination))
    assert response.status_code == 404
    assert await balance(client, existing) == Decimal("100.00")
    assert len((await history(client, existing))["data"]) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"amount": "0"},
        {"amount": "-1"},
        {"amount": "0.001"},
        {"amount": 1.5},
        {"source_account_id": "invalid"},
        {"destination_account_id": "invalid"},
        {"reference_id": " "},
        {"extra": True},
    ],
)
async def test_transfer_validation(client, changes):
    source, destination = await account(client), await account(client)
    payload = {**transfer_payload(source, destination), **changes}
    assert (await client.post("/api/v1/transfers", json=payload)).status_code == 422


async def test_self_transfer_rejected(client):
    source = await account(client)
    assert (
        await client.post("/api/v1/transfers", json=transfer_payload(source, source))
    ).status_code == 422


@pytest.mark.parametrize("conflict_side", ["source", "destination"])
async def test_either_leg_reference_conflict_rolls_back(client, conflict_side):
    source, destination = await account(client), await account(client)
    await entry(client, source, reference="funding")
    affected = source if conflict_side == "source" else destination
    await entry(client, affected, "1.00", reference="TRF-001")
    before = [await balance(client, source), await balance(client, destination)]
    counts = [len((await history(client, side))["data"]) for side in [source, destination]]
    response = await client.post("/api/v1/transfers", json=transfer_payload(source, destination))
    assert response.status_code == 409
    assert [await balance(client, source), await balance(client, destination)] == before
    assert [len((await history(client, side))["data"]) for side in [source, destination]] == counts


async def test_destination_overflow_rolls_back_source_debit(client):
    source, destination = await account(client), await account(client)
    await entry(client, source)
    await entry(client, destination, "9999999999999999.99")
    response = await client.post("/api/v1/transfers", json=transfer_payload(source, destination))
    assert response.status_code == 400
    assert await balance(client, source) == Decimal("100.00")
    assert await balance(client, destination) == Decimal("9999999999999999.99")
    assert len((await history(client, source))["data"]) == 1


async def test_reference_reuse_on_disjoint_transfer_pairs(client):
    a, b, c, d = [await account(client) for _ in range(4)]
    await entry(client, a)
    await entry(client, c)
    assert (await client.post("/api/v1/transfers", json=transfer_payload(a, b))).status_code == 201
    assert (await client.post("/api/v1/transfers", json=transfer_payload(c, d))).status_code == 201
    assert (await entry(client, b, reference="TRF-001")).status_code == 409
