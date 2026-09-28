from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import CurrentUserDep
from app.models.price_history import PriceHistory
from app.models.user import User
from app.schemas.price import LivePricesResponse, ManualRatesIn, PriceOut
from app.schemas.user import UserOut
from app.services.valuation import PURE_PURITY

router = APIRouter(prefix="/prices", tags=["prices"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/live", response_model=LivePricesResponse)
async def live_prices(_current: CurrentUserDep, session: SessionDep) -> LivePricesResponse:
    """Latest GoldAPI rate for every stored metal / purity / currency.

    Reads the cache the daily job fills — never calls GoldAPI.
    """
    stmt = (
        select(PriceHistory)
        .where(PriceHistory.source == "goldapi")
        .distinct(PriceHistory.metal, PriceHistory.purity, PriceHistory.currency)
        .order_by(
            PriceHistory.metal,
            PriceHistory.purity,
            PriceHistory.currency,
            PriceHistory.fetched_at.desc(),
        )
    )
    rows = (await session.execute(stmt)).scalars().all()
    return LivePricesResponse(prices=[PriceOut.model_validate(r) for r in rows])


@router.put("/manual", response_model=UserOut)
async def set_manual_rates(
    body: ManualRatesIn,
    current: CurrentUserDep,
    session: SessionDep,
) -> UserOut:
    """Save the user's own pure-metal rates.

    The profile columns hold the current rates used for valuation; each
    save is also appended to `price_history` so there's a record over time.
    Switching valuation to these rates is a separate setting
    (`default_pricing_mode`).
    """
    user = await session.get(User, current.id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not synced. Call POST /auth/sync first.",
        )

    user.manual_rates_currency = body.currency
    user.manual_gold_rate_per_gram = body.gold_rate_per_gram
    user.manual_silver_rate_per_gram = body.silver_rate_per_gram
    for metal, rate in (
        ("gold", body.gold_rate_per_gram),
        ("silver", body.silver_rate_per_gram),
    ):
        if rate is not None:
            session.add(
                PriceHistory(
                    metal=metal,
                    purity=PURE_PURITY[metal],
                    currency=body.currency,
                    rate_per_gram=rate,
                    source="manual",
                    user_id=user.id,
                )
            )
    await session.commit()
    await session.refresh(user)
    return UserOut.model_validate(user)
