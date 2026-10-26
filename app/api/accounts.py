from uuid import UUID

from fastapi import APIRouter

from app.core.database import Session
from app.schemas.account import AccountCreate, AccountRead, BalanceRead
from app.services import account_service

router = APIRouter(prefix="/accounts", tags=["Accounts"])


@router.post(
    "", response_model=AccountRead, status_code=201, summary="Create a zero-balance account"
)
async def create_account(payload: AccountCreate, session: Session):
    return await account_service.create_account(session, payload)


@router.get(
    "/{account_id}/balance", response_model=BalanceRead, summary="Get current account balance"
)
async def get_balance(account_id: UUID, session: Session):
    return await account_service.get_balance(session, account_id)
