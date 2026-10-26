import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.schemas.account import Money

MAX_MONEY = Decimal("9999999999999999.99")
TransactionType = Literal["credit", "debit"]
Reference = Annotated[
    str,
    StringConstraints(
        strict=True, strip_whitespace=True, min_length=1, max_length=100, pattern=r"^[^\x00]*$"
    ),
]
Description = Annotated[str, StringConstraints(strict=True, max_length=2000, pattern=r"^[^\x00]*$")]


def parse_amount(value: object) -> Decimal:
    # Require strings so the JSON parser never converts financial values to floats.
    if not isinstance(value, str) or not re.fullmatch(
        r"(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,2})?", value
    ):
        raise ValueError(
            "Amount must be a decimal string with at most 16 whole and 2 decimal digits"
        )
    return Decimal(value)


Amount = Annotated[
    Decimal,
    Field(gt=0, le=MAX_MONEY, max_digits=18, decimal_places=2),
    BeforeValidator(parse_amount, json_schema_input_type=str),
]


class TransactionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: TransactionType
    amount: Amount
    description: Description = ""
    reference_id: Reference


class TransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    account_id: UUID
    type: TransactionType
    amount: Money
    description: str
    reference_id: str
    created_at: datetime


class HistoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: TransactionType | None = None
    page: int = Field(default=1, ge=1, le=1_000_000)
    limit: int = Field(default=20, ge=1, le=100)


class Pagination(BaseModel):
    current_page: int
    page_size: int
    total_records: int
    total_pages: int


class TransactionHistory(BaseModel):
    data: list[TransactionRead]
    pagination: Pagination


class TransferCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_account_id: UUID
    destination_account_id: UUID
    amount: Amount
    reference_id: Reference
    description: Description = ""

    @model_validator(mode="after")
    def distinct_accounts(self):
        if self.source_account_id == self.destination_account_id:
            raise ValueError("Source and destination accounts must differ")
        return self


class TransferRead(BaseModel):
    source_transaction: TransactionRead
    destination_transaction: TransactionRead
