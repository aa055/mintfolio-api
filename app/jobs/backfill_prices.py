"""One-time historical backfill: metals.dev -> price_history (source='metalsdev').

    python -m app.jobs.backfill_prices --dry-run     # plan only, no API calls
    python -m app.jobs.backfill_prices               # ~5 years, ~61 calls
    python -m app.jobs.backfill_prices --years 1

metals.dev returns USD per troy ounce, at most 30 days per call, weekends
included. Rates are stored per gram of pure metal for each currency in
PRICE_CURRENCIES that is pegged to USD (USD, AED, SAR); others are skipped
until historical FX exists.

Safe to re-run: only windows with missing days are fetched, and existing
rows are left alone (ON CONFLICT DO NOTHING on the daily unique index).
Days missing *inside* the stored range are treated as gaps in the
provider's data (metals.dev has none for e.g. 25 Dec 2024 - 1 Jan 2025)
and skipped, so re-runs don't spend calls on them; --fill-gaps retries.
The free plan allows 100 calls/month, so a run that would need more than
--max-calls stops before calling anything.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal, engine
from app.models.price_history import PriceHistory
from app.services.price_history import USD_PEGS, price_day
from app.services.valuation import PURE_PURITY
from app.services.weight import GRAMS_PER_TROY_OZ

API_URL = "https://api.metals.dev/v1/timeseries"
WINDOW_DAYS = 30  # inclusive days per call — the API maximum
METALS = ("gold", "silver")
SOURCE = "metalsdev"


def windows(start: date, end: date) -> list[tuple[date, date]]:
    """Split [start, end] into consecutive windows of at most WINDOW_DAYS days."""
    out = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=WINDOW_DAYS - 1), end)
        out.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return out


def days_to_fetch(start: date, end: date, stored: set[date], *, fill_gaps: bool) -> set[date]:
    """Missing days in [start, end]. Without fill_gaps, only days before the
    earliest or after the latest stored day — interior holes are provider gaps."""
    all_days = {start + timedelta(days=i) for i in range((end - start).days + 1)}
    missing = all_days - stored
    if fill_gaps or not stored:
        return missing
    first, last = min(stored), max(stored)
    return {d for d in missing if d < first or d > last}


def rows_for_day(day: date, usd_per_toz: dict[str, float], currencies: list[str]) -> list[dict]:
    """price_history rows for one day: pure rate per gram, per metal and currency."""
    rows = []
    for metal in METALS:
        if usd_per_toz.get(metal) is None:
            continue
        usd_per_gram = Decimal(str(usd_per_toz[metal])) / GRAMS_PER_TROY_OZ
        for currency in currencies:
            rows.append(
                {
                    "metal": metal,
                    "purity": PURE_PURITY[metal],
                    "currency": currency,
                    "rate_per_gram": (usd_per_gram * USD_PEGS[currency]).quantize(
                        Decimal("0.0001")
                    ),
                    "source": SOURCE,
                    "user_id": None,
                    "fetched_at": datetime.combine(day, time.min, tzinfo=UTC),
                }
            )
    return rows


async def complete_days(
    session: AsyncSession, currencies: list[str], start: date, end: date
) -> set[date]:
    """Days that already have a metals.dev row for every metal and currency."""
    stmt = (
        select(price_day)
        .where(
            PriceHistory.source == SOURCE,
            PriceHistory.currency.in_(currencies),
            price_day.between(start, end),
        )
        .group_by(price_day)
        .having(func.count() >= len(METALS) * len(currencies))
    )
    return set((await session.execute(stmt)).scalars())


async def run(*, years: int, end: date, max_calls: int, dry_run: bool, fill_gaps: bool) -> int:
    try:
        return await _run(
            years=years, end=end, max_calls=max_calls, dry_run=dry_run, fill_gaps=fill_gaps
        )
    finally:
        await engine.dispose()


async def _run(*, years: int, end: date, max_calls: int, dry_run: bool, fill_gaps: bool) -> int:
    settings = get_settings()
    currencies = [c for c in settings.price_currencies_list if c in USD_PEGS]
    skipped = [c for c in settings.price_currencies_list if c not in USD_PEGS]
    if skipped:
        print(f"[backfill] skipping {skipped}: no historical FX yet (only USD-pegged currencies)")
    if not currencies:
        print("[backfill] nothing to do: no USD-pegged currency in PRICE_CURRENCIES")
        return 0

    start = end - timedelta(days=round(365.25 * years))
    async with SessionLocal() as session:
        done = await complete_days(session, currencies, start, end)
        wanted = days_to_fetch(start, end, done, fill_gaps=fill_gaps)
        todo = [
            (a, b)
            for a, b in windows(start, end)
            if any(a + timedelta(days=i) in wanted for i in range((b - a).days + 1))
        ]
        total_days = (end - start).days + 1
        gaps = total_days - len(done) - len(wanted)
        print(
            f"[backfill] {start} to {end} for {currencies}: "
            f"{len(done)} days already stored, {len(todo)} calls needed"
            + (f" ({gaps} provider-gap days skipped; --fill-gaps to retry)" if gaps else "")
        )
        if dry_run or not todo:
            return 0
        if len(todo) > max_calls:
            print(
                f"[backfill] refusing: {len(todo)} calls > --max-calls {max_calls} "
                "(free plan = 100/month)",
                file=sys.stderr,
            )
            return 1
        if not settings.metals_dev_key:
            print("[backfill] METALS_DEV_KEY is not set", file=sys.stderr)
            return 1

        inserted = 0
        async with httpx.AsyncClient(timeout=30.0) as client:
            for i, (a, b) in enumerate(todo, start=1):
                r = await client.get(
                    API_URL,
                    params={
                        "api_key": settings.metals_dev_key,
                        "start_date": a.isoformat(),
                        "end_date": b.isoformat(),
                    },
                )
                body = (
                    r.json()
                    if r.headers.get("content-type", "").startswith("application/json")
                    else {}
                )
                if r.status_code != 200 or body.get("status") != "success":
                    # Stop rather than burn quota on repeated failures; re-running resumes.
                    print(
                        f"[backfill] {a}..{b}: FAILED {r.status_code} {r.text[:200]}",
                        file=sys.stderr,
                    )
                    return 1

                rows = [
                    row
                    for day, entry in body.get("rates", {}).items()
                    for row in rows_for_day(date.fromisoformat(day), entry["metals"], currencies)
                ]
                if rows:
                    result = await session.execute(
                        insert(PriceHistory).values(rows).on_conflict_do_nothing()
                    )
                    await session.commit()
                    inserted += result.rowcount or 0
                print(f"[backfill] {i}/{len(todo)} {a}..{b}: {len(rows)} rows")
                await asyncio.sleep(0.5)  # be gentle with a free API

    print(f"[backfill] done: {inserted} rows inserted")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--years", type=int, default=5, help="how far back (default 5)")
    parser.add_argument(
        "--end",
        type=date.fromisoformat,
        default=datetime.now(UTC).date() - timedelta(days=1),
        help="last day to backfill (default: yesterday, UTC)",
    )
    parser.add_argument("--max-calls", type=int, default=70, help="abort if more are needed")
    parser.add_argument("--dry-run", action="store_true", help="plan only, no API calls")
    parser.add_argument(
        "--fill-gaps", action="store_true", help="also retry days missing inside the stored range"
    )
    args = parser.parse_args()
    sys.exit(
        asyncio.run(
            run(
                years=args.years,
                end=args.end,
                max_calls=args.max_calls,
                dry_run=args.dry_run,
                fill_gaps=args.fill_gaps,
            )
        )
    )


if __name__ == "__main__":
    main()
