from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models import Account, Transaction
from tests.helpers import account, balance, entry, history, transfer_payload


@pytest.mark.parametrize(
    "change",
    [
        {"amount": Decimal("0")},
        {"amount": Decimal("-1")},
        {"amount": Decimal("NaN")},
        {"type": "other"},
        {"reference_id": " "},
        {"account_id": uuid4()},
    ],
)
async def test_postgresql_rejects_invalid_ledger_rows(client, session_factory, change):
    account_id = await account(client)
    values = {
        "account_id": UUID(account_id),
        "type": "credit",
        "amount": Decimal("1.00"),
        "reference_id": "test",
        "description": "",
        **change,
    }
    with pytest.raises(IntegrityError):
        async with session_factory() as session, session.begin():
            session.add(Transaction(**values))
            await session.flush()
    assert not (await history(client, account_id))["data"]


async def test_postgresql_unique_reference_constraint(client, session_factory):
    account_id = await account(client)
    await entry(client, account_id)
    with pytest.raises(IntegrityError):
        async with session_factory() as session, session.begin():
            session.add(
                Transaction(
                    account_id=UUID(account_id),
                    type="credit",
                    amount=Decimal("1"),
                    reference_id="DEP-001",
                    description="",
                )
            )
            await session.flush()
    assert await balance(client, account_id) == Decimal("100.00")


@pytest.mark.parametrize("invalid", [Decimal("-0.01"), Decimal("NaN")])
async def test_postgresql_rejects_invalid_balances(client, session_factory, invalid):
    account_id = await account(client)
    with pytest.raises(IntegrityError):
        async with session_factory() as session, session.begin():
            row = await session.get(Account, UUID(account_id))
            row.balance = invalid
            await session.flush()


@pytest.mark.parametrize("operation", ["credit", "transfer"])
async def test_database_failure_rolls_back_entries_and_balances(client, engine, operation):
    source, destination = await account(client), await account(client)
    await entry(client, source)
    # A real PostgreSQL failure occurs during flush, after in-memory balances changed.
    # In a transfer this rejects its credit leg, exercising rollback of both accounts.
    async with engine.begin() as connection:
        await connection.execute(
            text("""
            ALTER TABLE transactions ADD CONSTRAINT test_injected_failure
            CHECK (reference_id <> 'FAIL-DB' OR type <> 'credit')
        """)
        )
    try:
        if operation == "credit":
            response = await entry(client, source, reference="FAIL-DB")
        else:
            response = await client.post(
                "/api/v1/transfers", json=transfer_payload(source, destination, reference="FAIL-DB")
            )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "INTEGRITY_CONFLICT"
        assert "test_injected_failure" not in response.text
        assert "INSERT" not in response.text
        assert await balance(client, source) == Decimal("100.00")
        assert await balance(client, destination) == Decimal("0.00")
        assert len((await history(client, source))["data"]) == 1
        assert not (await history(client, destination))["data"]
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("ALTER TABLE transactions DROP CONSTRAINT test_injected_failure")
            )
