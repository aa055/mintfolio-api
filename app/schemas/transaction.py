from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

TransactionKind = Literal["purchase", "sale"]


class TransactionOut(BaseModel):
    """One row of the combined activity feed.

    A purchase row is a whole dealer order; a sale row is one sold item.
    `purchase_id` always points at the order, so either row can link to it.
    """

    kind: TransactionKind
    date: date
    created_at: datetime
    purchase_id: UUID
    holding_id: UUID | None  # sales only
    title: str  # dealer for purchases, item label for sales
    detail: str  # item summary for purchases, buyer for sales
    currency: str
    amount: Decimal  # order total, or sale price
    realized_pl: Decimal | None  # sales only, when currencies match
    item_count: int  # purchases only (1 for sales)
    receipt_count: int  # purchases only
    metals: list[str]


class TransactionListOut(BaseModel):
    transactions: list[TransactionOut]
