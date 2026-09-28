"""GoldAPI.io client.

Only the daily job calls this — request handlers read `price_history`
instead, so user traffic never spends the free tier's 100 calls/month.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final

import httpx

from app.config import get_settings

GOLDAPI_BASE: Final = "https://www.goldapi.io/api"

_SYMBOLS: Final = {"gold": "XAU", "silver": "XAG"}

# GoldAPI `price_gram_<n>k` field -> the purity label we store.
_GOLD_PURITIES: Final = {
    "price_gram_24k": "24K",
    "price_gram_22k": "22K",
    "price_gram_21k": "21K",
    "price_gram_20k": "20K",
    "price_gram_18k": "18K",
    "price_gram_16k": "16K",
    "price_gram_14k": "14K",
    "price_gram_10k": "10K",
}
# For silver only the pure gram price is meaningful.
_SILVER_PURITIES: Final = {"price_gram_24k": "999"}


class GoldAPIError(Exception):
    """Raised when GoldAPI returns an error or an unexpected payload."""


@dataclass(frozen=True)
class Quote:
    metal: str
    purity: str
    currency: str
    rate_per_gram: Decimal
    fetched_at: datetime


async def fetch_quotes(client: httpx.AsyncClient, metal: str, currency: str) -> list[Quote]:
    """Fetch one metal/currency pair and return a quote per stored purity."""
    key = get_settings().goldapi_key
    if not key:
        raise GoldAPIError("GOLDAPI_KEY is not set")

    r = await client.get(
        f"{GOLDAPI_BASE}/{_SYMBOLS[metal]}/{currency}",
        headers={"x-access-token": key},
    )
    if r.status_code != 200:
        raise GoldAPIError(f"{metal}/{currency}: {r.status_code} {r.text[:200]}")
    body = r.json()

    fetched_at = datetime.fromtimestamp(body.get("timestamp") or 0, tz=UTC)
    fields = _GOLD_PURITIES if metal == "gold" else _SILVER_PURITIES
    quotes = [
        Quote(
            metal=metal,
            purity=purity,
            currency=currency,
            rate_per_gram=Decimal(str(body[field])).quantize(Decimal("0.0001")),
            fetched_at=fetched_at,
        )
        for field, purity in fields.items()
        if body.get(field) is not None
    ]
    if not quotes:
        raise GoldAPIError(f"{metal}/{currency}: no gram prices in response {body}")
    return quotes
