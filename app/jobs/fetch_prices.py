"""Daily price fetch: GoldAPI -> price_history.

Run on a schedule (Render cron) or by hand:

    python -m app.jobs.fetch_prices          # skips pairs already fetched today
    python -m app.jobs.fetch_prices --force  # fetch regardless

Costs 2 GoldAPI calls per configured currency (gold + silver).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, time

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal, engine
from app.models.price_history import PriceHistory
from app.services.goldapi import GoldAPIError, fetch_quotes
from app.services.price_history import price_day

METALS = ("gold", "silver")


async def _already_fetched_today(session: AsyncSession, metal: str, currency: str) -> bool:
    start_of_day = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    stmt = (
        select(PriceHistory.id)
        .where(
            PriceHistory.source == "goldapi",
            PriceHistory.metal == metal,
            PriceHistory.currency == currency,
            PriceHistory.created_at >= start_of_day,
        )
        .limit(1)
    )
    return (await session.execute(stmt)).first() is not None


async def run(*, force: bool = False) -> int:
    """Fetch every metal x currency pair. Returns the number of failed pairs."""
    failures = 0
    async with httpx.AsyncClient(timeout=20.0) as client, SessionLocal() as session:
        for currency in get_settings().price_currencies_list:
            for metal in METALS:
                if not force and await _already_fetched_today(session, metal, currency):
                    print(f"[prices] {metal}/{currency}: already fetched today, skipping")
                    continue
                try:
                    quotes = await fetch_quotes(client, metal, currency)
                except (GoldAPIError, httpx.HTTPError) as exc:
                    failures += 1
                    print(f"[prices] {metal}/{currency}: FAILED {exc}", file=sys.stderr)
                    continue
                # One snapshot per day: a re-run (e.g. --force) replaces that
                # day's rows instead of tripping the daily unique index.
                await session.execute(
                    delete(PriceHistory).where(
                        PriceHistory.source == "goldapi",
                        PriceHistory.metal == metal,
                        PriceHistory.currency == currency,
                        price_day == quotes[0].fetched_at.astimezone(UTC).date(),
                    )
                )
                session.add_all(
                    PriceHistory(
                        metal=q.metal,
                        purity=q.purity,
                        currency=q.currency,
                        rate_per_gram=q.rate_per_gram,
                        source="goldapi",
                        user_id=None,
                        fetched_at=q.fetched_at,
                    )
                    for q in quotes
                )
                # Commit per pair so one failure doesn't discard the others.
                await session.commit()
                print(f"[prices] {metal}/{currency}: stored {len(quotes)} purities")
    await engine.dispose()
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="fetch even if already fetched today")
    args = parser.parse_args()
    failures = asyncio.run(run(force=args.force))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
