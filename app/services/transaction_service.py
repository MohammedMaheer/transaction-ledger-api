from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import LedgerError
from app.models import Account, Transaction
from app.schemas.transaction import (
    MAX_MONEY,
    HistoryQuery,
    Pagination,
    TransactionCreate,
    TransactionHistory,
    TransactionRead,
    TransferCreate,
    TransferRead,
)


def duplicate_error() -> LedgerError:
    return LedgerError(
        409, "DUPLICATE_REFERENCE", "Reference ID already exists for an affected account"
    )


def translate_integrity_error(exc: IntegrityError) -> LedgerError:
    # asyncpg's diagnostic lives on the original driver's exception.
    cause = exc.orig.__cause__
    if getattr(cause, "constraint_name", None) == "uq_transactions_account_reference":
        return duplicate_error()
    return LedgerError(409, "INTEGRITY_CONFLICT", "Operation violates a database constraint")


async def lock_accounts(session: AsyncSession, account_ids: Sequence[UUID]) -> dict[UUID, Account]:
    # Every operation takes locks in the same UUID order, including opposite transfers.
    accounts = {}
    for account_id in sorted(set(account_ids)):
        account = await session.scalar(
            select(Account).where(Account.id == account_id).with_for_update()
        )
        if account is None:
            raise LedgerError(
                404, "ACCOUNT_NOT_FOUND", "Account not found", {"account_id": str(account_id)}
            )
        accounts[account_id] = account
    return accounts


async def check_reference(
    session: AsyncSession, account_ids: Sequence[UUID], reference: str
) -> None:
    existing = await session.scalar(
        select(Transaction.id)
        .where(Transaction.account_id.in_(account_ids), Transaction.reference_id == reference)
        .limit(1)
    )
    if existing is not None:
        raise duplicate_error()


def apply_entry(account: Account, entry: Transaction) -> None:
    if entry.type == "debit":
        if account.balance < entry.amount:
            raise LedgerError(400, "INSUFFICIENT_FUNDS", "Account has insufficient balance")
        account.balance -= entry.amount
    else:
        if account.balance > MAX_MONEY - entry.amount:
            raise LedgerError(
                400, "BALANCE_LIMIT_EXCEEDED", "Credit would exceed the balance limit"
            )
        account.balance += entry.amount


async def create_transaction(
    session: AsyncSession, account_id: UUID, payload: TransactionCreate
) -> TransactionRead:
    try:
        async with session.begin():
            accounts = await lock_accounts(session, [account_id])
            await check_reference(session, [account_id], payload.reference_id)
            entry = Transaction(account_id=account_id, **payload.model_dump())
            apply_entry(accounts[account_id], entry)
            session.add(entry)
            await session.flush()
            result = TransactionRead.model_validate(entry)
        return result
    except IntegrityError as exc:
        # The transaction context has already rolled back both the balance and entry.
        raise translate_integrity_error(exc) from exc


async def transfer(session: AsyncSession, payload: TransferCreate) -> TransferRead:
    try:
        async with session.begin():
            ids = [payload.source_account_id, payload.destination_account_id]
            accounts = await lock_accounts(session, ids)
            await check_reference(session, ids, payload.reference_id)
            common = {
                "amount": payload.amount,
                "reference_id": payload.reference_id,
                "description": payload.description,
            }
            debit = Transaction(account_id=ids[0], type="debit", **common)
            credit = Transaction(account_id=ids[1], type="credit", **common)
            apply_entry(accounts[ids[0]], debit)
            apply_entry(accounts[ids[1]], credit)
            session.add_all([debit, credit])
            await session.flush()
            result = TransferRead(
                source_transaction=TransactionRead.model_validate(debit),
                destination_transaction=TransactionRead.model_validate(credit),
            )
        return result
    except IntegrityError as exc:
        raise translate_integrity_error(exc) from exc


async def get_history(
    session: AsyncSession, account_id: UUID, query: HistoryQuery
) -> TransactionHistory:
    async with session.begin():
        # A short shared lock keeps count and page consistent with financial writers.
        account = await session.scalar(
            select(Account).where(Account.id == account_id).with_for_update(read=True)
        )
        if account is None:
            raise LedgerError(
                404, "ACCOUNT_NOT_FOUND", "Account not found", {"account_id": str(account_id)}
            )
        filters = [Transaction.account_id == account_id]
        if query.type is not None:
            filters.append(Transaction.type == query.type)
        total = await session.scalar(select(func.count()).select_from(Transaction).where(*filters))
        entries = await session.scalars(
            select(Transaction)
            .where(*filters)
            .order_by(Transaction.created_at.desc(), Transaction.id.desc())
            .offset((query.page - 1) * query.limit)
            .limit(query.limit)
        )
        return TransactionHistory(
            data=[TransactionRead.model_validate(entry) for entry in entries],
            pagination=Pagination(
                current_page=query.page,
                page_size=query.limit,
                total_records=total,
                total_pages=(total + query.limit - 1) // query.limit,
            ),
        )
