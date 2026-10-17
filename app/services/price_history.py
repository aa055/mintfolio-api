"""Daily market price history for charts and point-in-time lookups.

Two market sources feed `price_history`: the daily GoldAPI job and the
one-time metals.dev backfill. A day can have both, and GoldAPI wins.
Only the pure rate (24K gold, 999 silver) is read here; other purities
are scaled from it, the same way valuation does.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import Date, and_, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.price_history import PriceHistory
from app.services.valuation import PURE_PURITY

MARKET_SOURCES = ("goldapi", "metalsdev")

# Currencies pegged to USD, so USD history converts exactly.
USD_PEGS: dict[str, Decimal] = {
    "USD": Decimal("1"),
    "AED": Decimal("3.6725"),
    "SAR": Decimal("3.75"),
}

HistoryRange = Literal["1M", "3M", "6M", "YTD", "1Y", "5Y", "ALL"]

# Postgres: (fetched_at AT TIME ZONE 'UTC')::date — matches the daily unique index.
price_day = cast(func.timezone("UTC", PriceHistory.fetched_at), Date)


def range_start(range_: HistoryRange, today: date) -> date | None:
    """First day included in a chart range. None means all available history."""
    if range_ == "ALL":
        return None
    if range_ == "YTD":
        return date(today.year, 1, 1)
    days = {"1M": 30, "3M": 91, "6M": 182, "1Y": 365, "5Y": 1826}[range_]
    return today - timedelta(days=days)


def fill_daily(points: list[tuple[date, Decimal]]) -> list[tuple[date, Decimal]]:
    """Carry the last known rate across missing days (e.g. a skipped job run).

    Doesn't extend past the last known day: the series ends where data ends.
    """
    if not points:
        return []
    filled = [points[0]]
    for day, rate in points[1:]:
        prev_day, prev_rate = filled[-1]
        gap_day = prev_day + timedelta(days=1)
        while gap_day < day:
            filled.append((gap_day, prev_rate))
            gap_day += timedelta(days=1)
        filled.append((day, rate))
    return filled


async def daily_pure_rates_many(
    session: AsyncSession,
    pairs: set[tuple[str, str]],
    start: date | None = None,
) -> dict[tuple[str, str], list[tuple[date, Decimal]]]:
    """`daily_pure_rates` for several (metal, currency) pairs in ONE query.

    Each query is a full round trip to the database, so pages that need
    both metals (or several currencies) fetch them together.
    """
    if not pairs:
        return {}
    stmt = (
        select(
            PriceHistory.metal,
            PriceHistory.currency,
            price_day.label("day"),
            PriceHistory.rate_per_gram,
        )
        .where(
            or_(
                *(
                    and_(
                        PriceHistory.metal == metal,
                        PriceHistory.purity == PURE_PURITY[metal],
                        PriceHistory.currency == currency,
                    )
                    for metal, currency in pairs
                )
            ),
            PriceHistory.source.in_(MARKET_SOURCES),
        )
        .distinct(PriceHistory.metal, PriceHistory.currency, price_day)
        .order_by(
            PriceHistory.metal,
            PriceHistory.currency,
            price_day,
            case((PriceHistory.source == "goldapi", 0), else_=1),
            PriceHistory.fetched_at.desc(),
        )
    )
    if start is not None:
        stmt = stmt.where(PriceHistory.fetched_at >= datetime.combine(start, time.min, tzinfo=UTC))
    grouped: dict[tuple[str, str], list[tuple[date, Decimal]]] = {pair: [] for pair in pairs}
    for r in (await session.execute(stmt)).all():
        grouped[(r.metal, r.currency)].append((r.day, r.rate_per_gram))
    return {pair: fill_daily(points) for pair, points in grouped.items()}


async def daily_pure_rates(
    session: AsyncSession,
    metal: str,
    currency: str,
    start: date | None = None,
) -> tuple[list[tuple[date, Decimal]], set[str]]:
    """One pure rate per day (GoldAPI preferred, then the latest that day),
    with gaps carried forward. Also returns which sources contributed."""
    stmt = (
        select(price_day.label("day"), PriceHistory.rate_per_gram, PriceHistory.source)
        .where(
            PriceHistory.metal == metal,
            PriceHistory.purity == PURE_PURITY[metal],
            PriceHistory.currency == currency,
            PriceHistory.source.in_(MARKET_SOURCES),
        )
        .distinct(price_day)
        .order_by(
            price_day,
            case((PriceHistory.source == "goldapi", 0), else_=1),
            PriceHistory.fetched_at.desc(),
        )
    )
    if start is not None:
        stmt = stmt.where(PriceHistory.fetched_at >= datetime.combine(start, time.min, tzinfo=UTC))
    rows = (await session.execute(stmt)).all()
    return fill_daily([(r.day, r.rate_per_gram) for r in rows]), {r.source for r in rows}
