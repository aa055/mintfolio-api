from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.file import FileOut

# ---------------------------------------------------------------
# Enums (kept as Literals so they appear in OpenAPI as enums)
# ---------------------------------------------------------------

Metal = Literal["gold", "silver"]
Form = Literal["coin", "bar", "bullion", "jewelry", "round", "other"]
WeightUnit = Literal["g", "kg", "oz"]
PaymentMethod = Literal["cash", "card"]
HoldingStatus = Literal["active", "sold"]


# ---------------------------------------------------------------
# Holding (line item)
# ---------------------------------------------------------------


class HoldingCreate(BaseModel):
    """Input for one line item inside a purchase create request.

    `weight_grams` is *not* accepted from the client — the backend computes
    it from `weight_value × unit_factor` so the canonical value is always
    correct. The frontend should never trust its own conversion.
    """

    metal: Metal
    purity: Annotated[str | None, Field(default=None, max_length=20)]
    form: Form | None = None
    weight_value: Annotated[Decimal, Field(gt=Decimal("0"), max_digits=12, decimal_places=4)]
    weight_unit: WeightUnit
    quantity: Annotated[int, Field(default=1, ge=1)]
    brand: Annotated[str | None, Field(default=None, max_length=200)]
    purchase_price: Annotated[
        Decimal, Field(ge=Decimal("0"), max_digits=14, decimal_places=2)
    ]
    spot_rate_at_purchase: Annotated[
        Decimal | None,
        Field(default=None, ge=Decimal("0"), max_digits=14, decimal_places=4),
    ]
    premium_paid: Annotated[
        Decimal | None,
        Field(default=None, ge=Decimal("0"), max_digits=14, decimal_places=2),
    ]
    storage_location: Annotated[str | None, Field(default=None, max_length=200)]
    comments: Annotated[str | None, Field(default=None, max_length=2000)]


class HoldingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    metal: Metal
    purity: str | None
    form: Form | None
    weight_value: Decimal
    weight_unit: WeightUnit
    weight_grams: Decimal
    quantity: int
    brand: str | None
    purchase_price: Decimal
    spot_rate_at_purchase: Decimal | None
    premium_paid: Decimal | None
    storage_location: str | None
    status: HoldingStatus
    comments: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------
# Purchase
# ---------------------------------------------------------------


class PurchaseCreate(BaseModel):
    """Input for creating a multi-item purchase.

    Cross-field rule: `card_premium_percentage` is required for `card`
    payments and forbidden for `cash` payments. Matches the DB CHECK.
    """

    purchase_date: date
    dealer: Annotated[str | None, Field(default=None, max_length=200)]
    purchase_currency: Annotated[str, Field(min_length=3, max_length=3)]
    payment_method: PaymentMethod = "cash"
    card_premium_percentage: Annotated[
        Decimal | None,
        Field(default=None, ge=Decimal("0"), le=Decimal("100"), max_digits=5, decimal_places=2),
    ]
    notes: Annotated[str | None, Field(default=None, max_length=2000)]
    items: Annotated[list[HoldingCreate], Field(min_length=1)]

    @model_validator(mode="after")
    def _check_card_premium_consistency(self) -> PurchaseCreate:
        if self.payment_method == "cash" and self.card_premium_percentage is not None:
            raise ValueError(
                "card_premium_percentage must be null when payment_method is 'cash'."
            )
        if self.payment_method == "card" and self.card_premium_percentage is None:
            raise ValueError(
                "card_premium_percentage is required when payment_method is 'card'."
            )
        return self


class PurchaseOut(BaseModel):
    id: UUID
    portfolio_id: UUID
    purchase_date: date
    dealer: str | None
    purchase_currency: str
    payment_method: PaymentMethod
    card_premium_percentage: Decimal | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    items: list[HoldingOut]
    total_amount: Decimal
    files: list[FileOut] = Field(default_factory=list)


class PurchaseListResponse(BaseModel):
    purchases: list[PurchaseOut]
