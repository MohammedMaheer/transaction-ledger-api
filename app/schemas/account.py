from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, PlainSerializer, StringConstraints

Money = Annotated[Decimal, PlainSerializer(lambda value: format(value, ".2f"), return_type=str)]
AccountName = Annotated[
    str,
    StringConstraints(
        strict=True, strip_whitespace=True, min_length=1, max_length=200, pattern=r"^[^\x00]*$"
    ),
]


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: AccountName


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    balance: Money
    created_at: datetime


class BalanceRead(BaseModel):
    account_id: UUID
    balance: Money
