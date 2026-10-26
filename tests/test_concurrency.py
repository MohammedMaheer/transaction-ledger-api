import asyncio
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, text

from app.models import Account
from tests.helpers import account, balance, entry, history, transfer_payload


async def contend(session_factory, account_id, calls):
    """Hold a real DB row lock until every request is waiting on a PostgreSQL lock."""
    tasks = []
    try:
        async with session_factory() as blocker, blocker.begin():
            await blocker.scalar(
                select(Account).where(Account.id == UUID(account_id)).with_for_update()
            )
            tasks = [asyncio.create_task(call) for call in calls]
            async with asyncio.timeout(4):
                while True:
                    async with session_factory() as observer:
                        waiting = await observer.scalar(
                            text("""
                            SELECT count(*) FROM pg_stat_activity
                            WHERE datname = current_database()
                              AND application_name = 'transaction-ledger'
                              AND wait_event_type = 'Lock'
                        """)
                        )
                    if waiting >= len(tasks):
                        break
                    await asyncio.sleep(0.01)
        return await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_concurrent_debits_cannot_overspend(client, session_factory):
    account_id = await account(client)
    await entry(client, account_id)
    responses = await contend(
        session_factory,
        account_id,
        [entry(client, account_id, "30.00", "debit", f"debit-{i}") for i in range(8)],
    )
    assert sorted(response.status_code for response in responses) == [201] * 3 + [400] * 5
    assert await balance(client, account_id) == Decimal("10.00")
    assert len((await history(client, account_id))["data"]) == 4


async def test_concurrent_duplicate_credits_apply_once(client, session_factory):
    account_id = await account(client)
    responses = await contend(
        session_factory, account_id, [entry(client, account_id) for _ in range(8)]
    )
    assert sorted(response.status_code for response in responses) == [201] + [409] * 7
    assert await balance(client, account_id) == Decimal("100.00")
    assert len((await history(client, account_id))["data"]) == 1


async def test_concurrent_distinct_credits_have_no_lost_updates(client, session_factory):
    account_id = await account(client)
    responses = await contend(
        session_factory,
        account_id,
        [entry(client, account_id, "0.01", reference=str(i)) for i in range(8)],
    )
    assert all(response.status_code == 201 for response in responses)
    assert await balance(client, account_id) == Decimal("0.08")


async def test_concurrent_duplicate_transfers_apply_once(client, session_factory):
    source, destination = await account(client), await account(client)
    await entry(client, source)
    responses = await contend(
        session_factory,
        min(source, destination),
        [
            client.post("/api/v1/transfers", json=transfer_payload(source, destination))
            for _ in range(8)
        ],
    )
    assert sorted(response.status_code for response in responses) == [201] + [409] * 7
    assert await balance(client, source) == Decimal("70.00")
    assert await balance(client, destination) == Decimal("30.00")


async def test_opposite_direction_transfers_do_not_deadlock(client, session_factory):
    a, b = await account(client), await account(client)
    await entry(client, a)
    await entry(client, b)
    calls = []
    for i in range(4):
        calls.extend(
            [
                client.post("/api/v1/transfers", json=transfer_payload(a, b, "10.00", f"A-{i}")),
                client.post("/api/v1/transfers", json=transfer_payload(b, a, "10.00", f"B-{i}")),
            ]
        )
    responses = await contend(session_factory, min(a, b), calls)
    assert all(response.status_code == 201 for response in responses), [r.text for r in responses]
    assert await balance(client, a) == await balance(client, b) == Decimal("100.00")
    assert len((await history(client, a))["data"]) == len((await history(client, b))["data"]) == 9


async def test_lock_timeout_returns_safe_conflict_and_can_be_retried(client, session_factory):
    account_id = await account(client)
    async with session_factory() as blocker, blocker.begin():
        await blocker.scalar(
            select(Account).where(Account.id == UUID(account_id)).with_for_update()
        )
        response = await entry(client, account_id)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CONCURRENT_OPERATION"
        assert "SELECT" not in response.text
    assert await balance(client, account_id) == Decimal("0.00")
    assert not (await history(client, account_id))["data"]
    assert (await entry(client, account_id)).status_code == 201
