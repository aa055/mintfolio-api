from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models.user import User
from app.schemas.price import (
    HoldingValueOut,
    MetalSummaryOut,
    PortfolioSummaryOut,
    RateOut,
)
from app.services.portfolio_access import OwnedPortfolioDep
from app.services.valuation import load_holdings, rates_for_user, summarize

router = APIRouter(tags=["portfolios"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/portfolios/{portfolio_id}/summary", response_model=PortfolioSummaryOut)
async def portfolio_summary(
    portfolio: OwnedPortfolioDep,
    session: SessionDep,
) -> PortfolioSummaryOut:
    """Current value and P/L for the dashboard, in the user's preferred currency."""
    user = await session.get(User, portfolio.user_id)
    assert user is not None  # the portfolio FK guarantees it

    rates = await rates_for_user(session, user)
    s = summarize(await load_holdings(session, portfolio.id), user.preferred_currency, rates)

    return PortfolioSummaryOut(
        currency=s.currency,
        pricing_mode=user.default_pricing_mode,
        rates=[
            RateOut(
                metal=metal,
                rate_per_gram=r.rate_per_gram,
                currency=r.currency,
                source=r.source,
                fetched_at=r.fetched_at,
            )
            for (metal, currency), r in sorted(rates.items())
            if currency == user.preferred_currency
        ],
        total_value=s.total_value,
        cost_basis=s.cost_basis,
        total_invested=s.total_invested,
        unrealized_pl=s.unrealized_pl,
        unrealized_pl_pct=s.unrealized_pl_pct,
        realized_pl=s.realized_pl,
        active_count=s.active_count,
        sold_count=s.sold_count,
        unvalued_count=s.unvalued_count,
        other_currency_count=s.other_currency_count,
        by_metal=[
            MetalSummaryOut(
                metal=m.metal,
                grams=m.grams,
                current_value=m.current_value,
                cost_basis=m.cost_basis,
            )
            for m in s.by_metal.values()
        ],
        holdings=[
            HoldingValueOut(
                id=hv.id,
                current_value=hv.current_value,
                unrealized_pl=hv.unrealized_pl,
                realized_pl=hv.realized_pl,
            )
            for hv in s.holdings
        ],
    )
