from fastapi import APIRouter

from app.core.database import Session
from app.schemas.transaction import TransferCreate, TransferRead
from app.services import transaction_service

router = APIRouter(prefix="/transfers", tags=["Transfers"])


@router.post(
    "", response_model=TransferRead, status_code=201, summary="Atomically transfer between accounts"
)
async def create_transfer(payload: TransferCreate, session: Session):
    return await transaction_service.transfer(session, payload)
