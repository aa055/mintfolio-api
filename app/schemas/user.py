from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    """The application-side user profile as returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str | None
    avatar_url: str | None
    preferred_currency: str
    timezone: str
    default_pricing_mode: str
    manual_gold_rate_per_gram: Decimal | None
    manual_silver_rate_per_gram: Decimal | None
    manual_rates_currency: str | None
    created_at: datetime
    updated_at: datetime


class PortfolioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime


class MeResponse(BaseModel):
    user: UserOut
    portfolio: PortfolioOut


class AuthSyncRequest(BaseModel):
    """Optional profile fields the frontend may pass on first sync.

    The user id and email come from the verified JWT — never from this body.
    """

    display_name: str | None = Field(default=None, max_length=200)
    avatar_url: str | None = Field(default=None, max_length=2000)
