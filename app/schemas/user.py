from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.price import Currency


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


class UserSettingsUpdate(BaseModel):
    """Partial profile update — only the fields sent are changed."""

    display_name: str | None = Field(default=None, max_length=200)
    preferred_currency: Currency | None = None
    timezone: str | None = Field(default=None, max_length=64)
    default_pricing_mode: Literal["live", "manual"] | None = None

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown timezone: {v!r}") from exc
        return v

    @field_validator("preferred_currency", "timezone", "default_pricing_mode")
    @classmethod
    def _not_null(cls, v: object) -> object:
        # These columns are NOT NULL — sending null is a client bug, not "clear".
        if v is None:
            raise ValueError("may be omitted but not null")
        return v


class AuthSyncRequest(BaseModel):
    """Optional profile fields the frontend may pass on first sync.

    The user id and email come from the verified JWT — never from this body.
    """

    display_name: str | None = Field(default=None, max_length=200)
    avatar_url: str | None = Field(default=None, max_length=2000)
