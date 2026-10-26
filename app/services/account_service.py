from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import LedgerError
from app.models.account import Account
from app.schemas.account import AccountCreate, AccountRead, BalanceRead


async def require_account(session: AsyncSession, account_id: UUID) -> Account:
    account = await session.get(Account, account_id)
    if account is None:
        raise LedgerError(
            404, "ACCOUNT_NOT_FOUND", "Account not found", {"account_id": str(account_id)}
        )
    return account


async def create_account(session: AsyncSession, payload: AccountCreate) -> AccountRead:
    async with session.begin():
        account = Account(name=payload.name)
        session.add(account)
        await session.flush()
        result = AccountRead.model_validate(account)
    return result


async def get_balance(session: AsyncSession, account_id: UUID) -> BalanceRead:
    async with session.begin():
        account = await require_account(session, account_id)
        return BalanceRead(account_id=account.id, balance=account.balance)
