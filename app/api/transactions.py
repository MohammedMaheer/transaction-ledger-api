from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.core.database import Session
from app.schemas.transaction import (
    HistoryQuery,
    TransactionCreate,
    TransactionHistory,
    TransactionRead,
)
from app.services import transaction_service

router = APIRouter(prefix="/accounts/{account_id}/transactions", tags=["Transactions"])


@router.post("", response_model=TransactionRead, status_code=201, summary="Post a credit or debit")
async def create_transaction(account_id: UUID, payload: TransactionCreate, session: Session):
    return await transaction_service.create_transaction(session, account_id, payload)


@router.get(
    "", response_model=TransactionHistory, summary="Get filtered, paginated transaction history"
)
async def get_history(account_id: UUID, query: Annotated[HistoryQuery, Query()], session: Session):
    return await transaction_service.get_history(session, account_id, query)
