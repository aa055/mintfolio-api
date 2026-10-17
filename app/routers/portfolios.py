from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models.user import User
from app.schemas.price import (
    DayChangeOut,
    HoldingValueOut,
    MarketRateOut,
    MetalSummaryOut,
    PortfolioHistoryOut,
    PortfolioPointOut,
    PortfolioSummaryOut,
    RateOut,
)
from app.services.performance import (
    RateSeries,
    day_change,
    market_rates,
    portfolio_series,
    purchase_premium,
)
from app.services.portfolio_access import OwnedPortfolioDep
from app.services.price_history import HistoryRange, daily_pure_rates_many, range_start
from app.services.valuation import load_holdings, rates_for_user, summarize

router = APIRouter(tags=["portfolios"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# Enough history for "latest vs previous day" even across a long weekend.
_RECENT_DAYS = 14


async def _market_series(session: AsyncSession, currency: str, start: date | None) -> RateSeries:
    """Both metals' daily pure rates in `currency`, in one query."""
    series = await daily_pure_rates_many(session, {("gold", currency), ("silver", currency)}, start)
    return {metal: series[(metal, currency)] for metal in ("gold", "silver")}


@router.get("/portfolios/{portfolio_id}/summary", response_model=PortfolioSummaryOut)
async def portfolio_summary(
    portfolio: OwnedPortfolioDep,
    session: SessionDep,
) -> PortfolioSummaryOut:
    """Current value and P/L for the dashboard, in the user's preferred currency."""
    user = await session.get(User, portfolio.user_id)
    assert user is not None  # the portfolio FK guarantees it
    currency = user.preferred_currency

    rates = await rates_for_user(session, user)
    holdings = await load_holdings(session, portfolio.id)
    s = summarize(holdings, currency, rates)

    # One price query covers both needs (every query is a full DB round trip):
    # the last few days for the rate cards / "Today", and each purchase date
    # for premium-over-spot (lots with their own spot rate don't need one).
    recent_start = datetime.now(UTC).date() - timedelta(days=_RECENT_DAYS)
    needs_history = [h for h in holdings if not h.spot_rate_at_purchase and h.purchase_date]
    pairs = {("gold", currency), ("silver", currency)} | {
        (h.metal, h.currency) for h in needs_history
    }
    start = min([recent_start, *(h.purchase_date for h in needs_history if h.purchase_date)])
    series = await daily_pure_rates_many(session, pairs, start)

    recent: RateSeries = {
        metal: [p for p in series[(metal, currency)] if p[0] >= recent_start]
        for metal in ("gold", "silver")
    }
    # "Today" compares market prices, so it's meaningless with manual rates.
    change = day_change(holdings, currency, recent) if user.default_pricing_mode == "live" else None
    purchase_rates = {pair: dict(points) for pair, points in series.items()}
    premiums = {h.id: purchase_premium(h, purchase_rates) for h in holdings}

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
            for (metal, rate_currency), r in sorted(rates.items())
            if rate_currency == currency
        ],
        market_rates=[
            MarketRateOut(
                metal=m.metal,
                currency=currency,
                day=m.day,
                rate_per_gram=m.rate_per_gram,
                previous_day=m.previous_day,
                previous_rate=m.previous_rate,
                change_pct=m.change_pct,
            )
            for m in market_rates(recent)
        ],
        total_value=s.total_value,
        cost_basis=s.cost_basis,
        total_invested=s.total_invested,
        unrealized_pl=s.unrealized_pl,
        unrealized_pl_pct=s.unrealized_pl_pct,
        realized_pl=s.realized_pl,
        all_time_pl=s.all_time_pl,
        all_time_pl_pct=s.all_time_pl_pct,
        today_change=(
            DayChangeOut(
                day=change.day,
                previous_day=change.previous_day,
                amount=change.amount,
                pct=change.pct,
            )
            if change
            else None
        ),
        active_count=s.active_count,
        sold_count=s.sold_count,
        unvalued_count=s.unvalued_count,
        other_currency_count=s.other_currency_count,
        by_metal=[
            MetalSummaryOut(
                metal=m.metal,
                grams=m.grams,
                pure_grams=m.pure_grams.quantize(Decimal("0.01")),
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
                **(
                    {
                        "melt_value_at_purchase": prem.melt_value,
                        "premium": prem.amount,
                        "premium_pct": prem.pct,
                        "premium_source": prem.source,
                    }
                    if (prem := premiums.get(hv.id))
                    else {}
                ),
            )
            for hv in s.holdings
        ],
    )


@router.get("/portfolios/{portfolio_id}/history", response_model=PortfolioHistoryOut)
async def portfolio_history(
    portfolio: OwnedPortfolioDep,
    session: SessionDep,
    range_: Annotated[HistoryRange, Query(alias="range")] = "ALL",
) -> PortfolioHistoryOut:
    """Daily value vs invested for the performance chart, at market rates.

    Starts at the first purchase (or the range start, if later). Holdings
    bought in other currencies are left out, as in the summary.
    """
    user = await session.get(User, portfolio.user_id)
    assert user is not None
    currency = user.preferred_currency

    holdings = await load_holdings(session, portfolio.id)
    purchase_dates = [
        h.purchase_date for h in holdings if h.currency == currency and h.purchase_date
    ]
    if not purchase_dates:
        return PortfolioHistoryOut(currency=currency, range=range_, points=[])

    today = datetime.now(UTC).date()
    start = range_start(range_, today)
    first = min(purchase_dates)
    rates = await _market_series(session, currency, max(start, first) if start else first)
    points = portfolio_series(holdings, currency, rates, start, end=today)
    return PortfolioHistoryOut(
        currency=currency,
        range=range_,
        points=[
            PortfolioPointOut(day=p.day, value=p.value, invested=p.invested, realized=p.realized)
            for p in points
        ],
    )
