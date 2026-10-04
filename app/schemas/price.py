from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Currency = Literal["AED", "USD", "EUR", "GBP", "SAR", "INR"]

Rate = Annotated[
    Decimal | None,
    Field(default=None, gt=Decimal("0"), max_digits=14, decimal_places=4),
]


class PriceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    metal: str
    purity: str
    currency: str
    rate_per_gram: Decimal
    source: str
    fetched_at: datetime


class LivePricesResponse(BaseModel):
    prices: list[PriceOut]


class ManualRatesIn(BaseModel):
    """Per-gram rates for PURE metal (24K gold, .999 silver). Lower purities
    are scaled from these, same as live pricing."""

    currency: Currency
    gold_rate_per_gram: Rate
    silver_rate_per_gram: Rate

    @model_validator(mode="after")
    def _at_least_one(self) -> ManualRatesIn:
        if self.gold_rate_per_gram is None and self.silver_rate_per_gram is None:
            raise ValueError("Provide at least one of gold_rate_per_gram / silver_rate_per_gram.")
        return self


class RateOut(BaseModel):
    metal: str
    rate_per_gram: Decimal
    currency: str
    source: str
    fetched_at: datetime | None


class MetalSummaryOut(BaseModel):
    metal: str
    grams: Decimal
    current_value: Decimal
    cost_basis: Decimal


class HoldingValueOut(BaseModel):
    id: UUID
    current_value: Decimal | None
    unrealized_pl: Decimal | None
    realized_pl: Decimal | None


class PortfolioSummaryOut(BaseModel):
    currency: str
    pricing_mode: str
    rates: list[RateOut]
    total_value: Decimal
    cost_basis: Decimal
    total_invested: Decimal
    unrealized_pl: Decimal
    unrealized_pl_pct: Decimal | None
    realized_pl: Decimal
    active_count: int
    sold_count: int
    unvalued_count: int
    other_currency_count: int
    by_metal: list[MetalSummaryOut]
    holdings: list[HoldingValueOut]


class PricePoint(BaseModel):
    day: date
    rate_per_gram: Decimal


class PriceHistoryResponse(BaseModel):
    """Daily pure-metal rate (24K gold / 999 silver) per gram. Missing days
    are carried forward from the previous day."""

    metal: str
    purity: str
    currency: str
    range: str
    points: list[PricePoint]
    sources: list[str]
